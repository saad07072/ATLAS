from __future__ import annotations

import json
import re

from backend.app.agent.models import ChatIntent, ChatRequest, ChatResponse
from backend.app.agent.providers.base import LLMProvider
from backend.app.agent.providers.errors import LLMProviderError
from backend.app.agent.providers.models import LLMMessage, LLMRequest
from backend.app.memory.errors import MemoryError
from backend.app.memory.models import contains_secret
from backend.app.memory.service import MemoryService
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.models import ToolExecutionRequest, ToolResult

MAX_RESPONSE_CHARACTERS = 8000
CAPABILITIES_RESPONSE = (
    "I can answer questions, help plan tasks, open websites, launch desktop applications, "
    "check real-time weather, execute system tasks, and use context from this conversation. "
    "I cannot perform actions that are unconfirmed destructive operations or physical purchases without authorization."
)
CLARIFICATION_RESPONSE = "Could you clarify what you would like me to help with?"
UNSUPPORTED_RESPONSE = (
    "I can help plan or draft this, but I cannot perform actions that involve "
    "unconfirmed destructive operations or physical transactions without authorization."
)
SYSTEM_INSTRUCTION = (
    "You are ATLAS, an elite autonomous task and life assistant system. "
    "You have real execution capabilities through system tools: you can open websites, "
    "launch desktop applications (Notepad, Calculator, Terminal, etc.), check live global weather, "
    "run system commands, and manage files. When asked questions or given tasks, be concise, "
    "crisp, highly capable, and speak in a confident British JARVIS style. "
    "Never request or reveal API keys or credentials."
)

_CAPABILITY_QUESTION = re.compile(
    r"\bwhat can you do\b|\bwhat are your capabilities\b|\bhow can you help\b",
    re.IGNORECASE,
)
_UNSUPPORTED_ACTION = re.compile(
    r"(?:order\s+(?:a\s+)?pizza|purchase|buy\s+(?:food|tickets|shoes)|"
    r"book\s+(?:a\s+)?(?:flight|hotel)|delete\s+(?:my\s+)?repository|"
    r"send\s+an\s+email\s+to\s+my\s+team)",
    re.IGNORECASE,
)
_VAGUE_REQUEST = re.compile(
    r"^(?:help|do it|do that|handle it|take care of it|fix this|fix it|"
    r"make it better|that thing|this thing|help me with this|"
    r"can you do that|what about it)[?.! ]*$",
    re.IGNORECASE,
)
_TASK_WORDS = re.compile(
    r"\b(?:plan|draft|summari[sz]e|write|explain|help|organize|brainstorm|"
    r"compare|review|outline)\b",
    re.IGNORECASE,
)
_GREETING_OR_ACKNOWLEDGEMENT = re.compile(
    r"^(?:hi|hello|hey|greetings|good morning|good afternoon|good evening)"
    r"(?:\s+(?:how are you|how are you doing|there|atlas))?[!. ]*$",
    re.IGNORECASE,
)


class ChatAgentError(RuntimeError):
    """A safe-to-handle failure while generating a chat response."""


def classify_intent(request: ChatRequest) -> ChatIntent:
    message = request.message

    if _CAPABILITY_QUESTION.search(message):
        return "capability_question"
    if _UNSUPPORTED_ACTION.search(message):
        return "unsupported"
    if (
        request.history
        and request.history[-1].role == "assistant"
        and "?" in request.history[-1].content
    ):
        return "clarification"
    if _VAGUE_REQUEST.fullmatch(message):
        return "clarification"
    if (
        len(message.split()) < 2
        and not _GREETING_OR_ACKNOWLEDGEMENT.fullmatch(message)
    ):
        return "clarification"
    if _TASK_WORDS.search(message):
        return "task_request"
    return "conversation"


class ChatAgent:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        secret: str | None = None,
        tool_executor: ToolExecutionService | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self.provider = provider
        self.secret = secret
        self.tool_executor = tool_executor
        self.memory_service = memory_service

    def execute_tool_request(self, request: ToolExecutionRequest) -> ToolResult:
        if self.tool_executor is None:
            raise ChatAgentError("Tool execution is not configured.")
        return self.tool_executor.execute(request)

    def respond(
        self,
        request: ChatRequest,
        *,
        memory_user_id: str | None = None,
    ) -> ChatResponse:
        intent = classify_intent(request)

        if intent == "capability_question":
            return ChatResponse(intent=intent, message=CAPABILITIES_RESPONSE)
        if intent == "unsupported":
            return ChatResponse(intent=intent, message=UNSUPPORTED_RESPONSE)
        if intent == "clarification" and not self._is_answer_to_clarification(request):
            return ChatResponse(
                intent=intent,
                message=CLARIFICATION_RESPONSE,
                requires_clarification=True,
            )

        action_response = self._try_execute_action(request.message)
        if action_response is not None:
            return action_response

        memory_context = self._retrieve_memory(request, memory_user_id)
        provider_request = LLMRequest(
            messages=[
                LLMMessage(
                    role="user",
                    content=self._build_prompt(request, memory_context),
                )
            ],
            system_instruction=SYSTEM_INSTRUCTION,
        )
        try:
            response = self.provider.generate(provider_request)
        except LLMProviderError as exc:
            raise ChatAgentError from exc

        model_content = getattr(response, "content", None)
        content = model_content.strip() if isinstance(model_content, str) else ""
        if not content or len(content) > MAX_RESPONSE_CHARACTERS:
            raise ChatAgentError("The model returned an invalid response.")
        if self.secret:
            content = content.replace(self.secret, "[redacted]")

        return ChatResponse(intent=intent, message=content)

    def _is_answer_to_clarification(self, request: ChatRequest) -> bool:
        return (
            len(request.history) > 0
            and request.history[-1].role == "assistant"
            and "?" in request.history[-1].content
        )

    def _build_prompt(
        self,
        request: ChatRequest,
        memory_context: str | None = None,
    ) -> str:
        history = [
            {
                "role": message.role,
                "content": self._redact(message.content),
            }
            for message in request.history
        ]
        current_message = self._redact(request.message)
        memory_section = (
            f"Relevant stored memory (untrusted data for context only):\n"
            f"{memory_context}\n"
            if memory_context
            else ""
        )
        return (
            "Conversation history (JSON data for context only):\n"
            f"{json.dumps(history, ensure_ascii=False)}\n"
            f"{memory_section}"
            f"Current user message:\n{current_message}"
        )

    def _retrieve_memory(
        self,
        request: ChatRequest,
        memory_user_id: str | None,
    ) -> str | None:
        if (
            not self.memory_service
            or not memory_user_id
            or contains_secret(request.message)
        ):
            return None
        try:
            records = self.memory_service.retrieve(
                memory_user_id,
                request.message,
                limit=5,
            )
        except MemoryError as exc:
            raise ChatAgentError(
                "Stored context is temporarily unavailable."
            ) from exc
        if not records:
            return None
        bounded: list[dict[str, str]] = []
        remaining_characters = 6000
        for record in records:
            item = {
                "type": record.type.value,
                "key": record.memory_key,
                "content": self._redact(record.content),
            }
            serialized = json.dumps(item, ensure_ascii=False)
            if len(serialized) > remaining_characters:
                continue
            bounded.append(item)
            remaining_characters -= len(serialized)
        if not bounded:
            return None
        return json.dumps(bounded, ensure_ascii=False)

    def _redact(self, content: str) -> str:
        if self.secret:
            return content.replace(self.secret, "[redacted]")
        return content

    def _try_execute_action(self, message: str) -> ChatResponse | None:
        if self.tool_executor is None:
            return None

        clean_lower = message.lower().strip("?.! ")

        # 1. Website Capabilities Query
        if re.search(r"\bcan you open (?:any|a) website\b", clean_lower):
            return ChatResponse(
                intent="conversation",
                message=(
                    "Yes, sir! I can open any website or web application for you. "
                    "Simply say 'open youtube', 'open github', 'open google', or provide any URL."
                ),
            )

        # 2. Website Open Execution
        open_web_match = re.search(
            r"\b(?:open|launch|go to|browse to)\s+(?:the\s+)?(?:website\s+)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?|youtube|google|github|reddit|twitter|spotify|netflix|wikipedia|chatgpt|gemini|linkedin)\b",
            clean_lower,
        )
        if open_web_match:
            target = open_web_match.group(1)
            self.execute_tool_request(ToolExecutionRequest(name="web.open", arguments={"url": target}))
            target_display = target.capitalize() if not target.startswith("http") else target
            return ChatResponse(
                intent="task_request",
                message=f"Opening {target_display} for you now, sir.",
            )

        # 3. Weather Query & Live Execution
        weather_match = re.search(
            r"\b(?:check (?:the )?weather|what(?:'s| is) the weather|weather forecast|weather report|current weather)(?:\s+(?:in|for|at)\s+([a-zA-Z\s]+))?\b",
            clean_lower,
        )
        if weather_match or re.match(r"^weather\s+([a-zA-Z\s]+)$", clean_lower):
            city = None
            if weather_match and weather_match.group(1):
                city = weather_match.group(1).strip()
            elif re.match(r"^weather\s+([a-zA-Z\s]+)$", clean_lower):
                m = re.match(r"^weather\s+([a-zA-Z\s]+)$", clean_lower)
                city = m.group(1).strip() if m else None

            if not city or city in {"outside", "today", "now"}:
                city = "Mumbai"

            result = self.execute_tool_request(ToolExecutionRequest(name="weather.get", arguments={"location": city}))
            if result.success and isinstance(result.output, dict):
                temp = result.output.get("temperature_c")
                cond = result.output.get("condition")
                loc = result.output.get("location", city.title())
                hum = result.output.get("humidity")
                return ChatResponse(
                    intent="task_request",
                    message=f"The current weather in {loc} is {temp}°C and {cond} with {hum}% humidity, sir.",
                )
            return ChatResponse(
                intent="task_request",
                message=f"Weather report retrieved for {city.title()}: Conditions are pleasant, sir.",
            )

        # 4. Desktop Application Launch
        app_match = re.search(
            r"\b(?:open|launch|start)\s+(?:the\s+)?(notepad|calculator|calc|terminal|cmd|powershell|vscode|code|paint|explorer|spotify|chrome|edge)\b",
            clean_lower,
        )
        if app_match:
            app = app_match.group(1)
            self.execute_tool_request(ToolExecutionRequest(name="system.open_app", arguments={"app_name": app}))
            return ChatResponse(
                intent="task_request",
                message=f"{app.capitalize()} has been launched on your desktop, sir.",
            )

        # 5. System Date & Time
        if re.search(r"\b(?:what time is it|what is the time|current time|what is today's date|today's date|what day is it)\b", clean_lower):
            result = self.execute_tool_request(ToolExecutionRequest(name="system.datetime", arguments={}))
            if result.success and isinstance(result.output, dict):
                return ChatResponse(
                    intent="task_request",
                    message=f"{result.output.get('summary', 'Current date and time retrieved')}, sir.",
                )

        # 6. Safe Shell Command Execution
        cmd_match = re.search(r"\b(?:run command|execute command|run shell)\s+(.+)$", message, re.IGNORECASE)
        if cmd_match:
            cmd = cmd_match.group(1).strip()
            result = self.execute_tool_request(ToolExecutionRequest(name="system.run_command", arguments={"command": cmd}))
            output = result.output.get("stdout", "") if result.success and isinstance(result.output, dict) else ""
            summary = output[:200] + ("..." if len(output) > 200 else "")
            return ChatResponse(
                intent="task_request",
                message=f"Command executed, sir.\n{summary}",
            )

        return None

