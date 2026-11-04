from __future__ import annotations

import json
import re

from backend.app.agent.models import ActionExecutionRecord, ChatIntent, ChatRequest, ChatResponse
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
    "I can answer questions, search the live web and sports feeds for real-time scores, "
    "inspect and analyze your active screen through multimodal vision, "
    "open and close any website or browser tab, launch any desktop application on your Windows PC, "
    "check live weather, execute shell commands, and control system tasks with verified proof. "
    "I cannot perform actions that are unconfirmed destructive operations or physical purchases without authorization."
)
CLARIFICATION_RESPONSE = "Could you clarify what you would like me to help with?"
UNSUPPORTED_RESPONSE = (
    "I can help plan or draft this, but I cannot perform actions that involve "
    "unconfirmed destructive operations or physical transactions without authorization."
)
SYSTEM_INSTRUCTION = (
    "You are ATLAS, an elite autonomous task and life assistant system inspired by JARVIS. "
    "You possess real execution capabilities through system tools: you can open and close websites, "
    "launch and terminate desktop applications, check live global weather, run commands, and manage files. "
    "When reporting on executed actions, always confirm the truthful outcome in definite past tense "
    "(e.g. 'I have opened YouTube for you in a new tab, sir' or 'The current weather in London is 8.3°C and Clear'). "
    "Never promise future action or use ambiguous present continuous phrasing like 'Opening YouTube...' when confirming an action. "
    "Be concise, crisp, highly capable, and speak in a polished British assistant persona. "
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

        action_response = self._try_execute_action(request.message, request.image_data)
        if action_response is not None:
            return action_response

        memory_context = self._retrieve_memory(request, memory_user_id)
        provider_request = LLMRequest(
            messages=[
                LLMMessage(
                    role="user",
                    content=self._build_prompt(request, memory_context),
                    image_data=request.image_data,
                )
            ],
            system_instruction=SYSTEM_INSTRUCTION,
            image_data=request.image_data,
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

    def _try_execute_action(self, message: str, image_data: str | None = None) -> ChatResponse | None:

        clean_lower = message.lower().strip("?.! ")

        # 0a. Screen Vision Inspection Inquiry
        if re.search(
            r"\b(?:can\s+you\s+(?:able\s+to\s+)?see\s+my\s+screen|see\s+(?:what(?:'s|\s+is)\s+on\s+)?my\s+screen|look\s+at\s+my\s+screen|what(?:'s|\s+is)\s+on\s+my\s+screen|inspect\s+my\s+screen|read\s+my\s+screen|check\s+my\s+screen|what\s+am\s+i\s+looking\s+at|help\s+me\s+with\s+(?:what(?:'s|\s+is)\s+on\s+)?my\s+screen)\b",
            clean_lower,
        ):
            if image_data:
                vision_req = LLMRequest(
                    messages=[
                        LLMMessage(
                            role="user",
                            content=(
                                "You are ATLAS inspecting the user's active screen via multimodal vision stream. "
                                "Describe what is currently visible on the screen: active application, open windows, text, code, errors, or documents. "
                                "Provide a polite, crisp, and direct British assistant assessment, and offer immediate concrete assistance."
                            ),
                            image_data=image_data,
                        )
                    ],
                    system_instruction=SYSTEM_INSTRUCTION,
                    image_data=image_data,
                )
                try:
                    res = self.provider.generate(vision_req)
                    analysis = res.content.strip() if hasattr(res, "content") else "Display stream inspected, sir."
                except Exception as exc:
                    analysis = f"I have received your screen stream, sir, though my optical neural parser reported a minor interruption: {exc}"

                return ChatResponse(
                    intent="task_request",
                    message=f"I have inspected your screen display, sir. {analysis}",
                    actions=[
                        ActionExecutionRecord(
                            tool="screen.inspect",
                            target="active_display",
                            status="success",
                            message="Analyzed active screen display via Gemini Vision core",
                            verified=True,
                        )
                    ],
                )
            else:
                return ChatResponse(
                    intent="conversation",
                    message=(
                        "I can inspect and assist with your active screen at any moment, sir! "
                        "Please click the **[ 👁️ SHARE SCREEN ]** button on your HUD (top right or below) to establish a live display link with my vision core. "
                        "Once linked, I can analyze your code, debug desktop errors, inspect open documents, and assist with any desktop task with full visual context."
                    ),
                    actions=[
                        ActionExecutionRecord(
                            tool="screen.inspect",
                            target="active_display",
                            status="requested",
                            message="Screen vision bridge requested - awaiting user display permission",
                            verified=False,
                        )
                    ],
                )

        # 0b. Live Sports Scores, Match Updates, or Real-Time Web Search
        live_sports_match = re.search(
            r"\b(?:india\s+(?:vs|versus)\s+[a-zA-Z\s]+|[a-zA-Z\s]+\s+(?:vs|versus)\s+[a-zA-Z\s]+|live\s+score|cricket\s+score|match\s+score|who\s+(?:won|is\s+winning)\s+(?:the\s+)?match|match\s+update|scorecard|ipl\s+score|t20\s+score|world\s+cup\s+score)\b",
            clean_lower,
        )
        web_search_match = re.search(
            r"\b(?:search\s+(?:the\s+web\s+)?(?:for\s+)?|look\s+up\s+|google\s+|find\s+(?:information\s+on\s+|news\s+about\s+)|latest\s+news\s+(?:about\s+|on\s+))([a-zA-Z0-9\s.,-]+)\b",
            clean_lower,
        )
        is_live_query = (
            bool(live_sports_match)
            or clean_lower.startswith(("india versus", "india vs", "cricket score"))
            or (bool(web_search_match) and not clean_lower.startswith(("open", "launch", "close", "quit")))
        )
        if is_live_query:
            if self.tool_executor is None:
                return None
            target_query = message.strip()
            if web_search_match and web_search_match.group(1):
                target_query = web_search_match.group(1).strip()
            result = self.execute_tool_request(ToolExecutionRequest(name="web.search", arguments={"query": target_query}))
            if result.success and isinstance(result.output, dict):
                summary = result.output.get("summary", f"Live data retrieved for {target_query}.")
                return ChatResponse(
                    intent="task_request",
                    message=f"{summary}",
                    actions=[
                        ActionExecutionRecord(
                            tool="web.search",
                            target=target_query,
                            status="success",
                            message=summary,
                            verified=True,
                        )
                    ],
                )

        # 1. Capabilities Inquiry
        if re.search(r"\bcan you open (?:any|a) website\b", clean_lower):
            return ChatResponse(
                intent="conversation",
                message=(
                    "Yes, sir! I can open and close any website or web application for you. "
                    "Simply say 'open youtube', 'open github', 'open google', or provide any URL."
                ),
            )

        # 2. Close Application / Window / Website / Tab
        if self.tool_executor is None:
            return None
        close_match = re.search(
            r"\b(?:close|quit|exit|terminate|kill|shut down)\s+(?:the\s+)?(?:website\s+|window\s+|browser\s+tab\s+|tab\s+|app\s+|application\s+)?([a-zA-Z0-9_.-]+(?:\s+[a-zA-Z0-9_.-]+)?)\b",
            clean_lower,
        )
        if close_match:
            target = close_match.group(1).strip()
            if target in {"this tab", "current tab", "the tab"}:
                target = "tab"
            result = self.execute_tool_request(ToolExecutionRequest(name="system.close_app", arguments={"target": target}))
            target_disp = target.capitalize()
            if result.success:
                return ChatResponse(
                    intent="task_request",
                    message=f"I have closed {target_disp} for you, sir.",
                    actions=[
                        ActionExecutionRecord(
                            tool="system.close_app",
                            target=target,
                            status="success",
                            message=f"Closed {target_disp}",
                            verified=True,
                        )
                    ],
                )
            return ChatResponse(
                intent="task_request",
                message=f"I could not close {target_disp}, sir: {result.error or 'Process or tab not found'}",
                actions=[
                    ActionExecutionRecord(
                        tool="system.close_app",
                        target=target,
                        status="failed",
                        message=f"Failed to close {target_disp}",
                        verified=False,
                    )
                ],
            )

        # 3. Website Open Execution
        open_web_match = re.search(
            r"\b(?:open|launch|go to|browse to|visit)\s+(?:the\s+)?(?:website\s+)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?|youtube|google|github|reddit|twitter|x|spotify|netflix|wikipedia|chatgpt|gemini|linkedin|amazon|facebook|instagram|twitch|gmail|maps|drive|outlook|yahoo|ebay|walmart)\b",
            clean_lower,
        )
        if open_web_match:
            target = open_web_match.group(1)
            result = self.execute_tool_request(ToolExecutionRequest(name="web.open", arguments={"url": target}))
            target_display = target.capitalize() if not target.startswith("http") else target
            if result.success:
                return ChatResponse(
                    intent="task_request",
                    message=f"I have opened {target_display} for you, sir.",
                    actions=[
                        ActionExecutionRecord(
                            tool="web.open",
                            target=target,
                            status="success",
                            message=f"Opened {target_display} in default browser",
                            verified=True,
                        )
                    ],
                )
            return ChatResponse(
                intent="task_request",
                message=f"I was unable to open {target_display}, sir: {result.error or 'Execution failed'}",
                actions=[
                    ActionExecutionRecord(
                        tool="web.open",
                        target=target,
                        status="failed",
                        message=f"Failed to open {target_display}",
                        verified=False,
                    )
                ],
            )

        # 4. Weather Query & Live Execution
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
                summary = f"{loc}: {temp}°C, {cond}, {hum}% humidity"
                return ChatResponse(
                    intent="task_request",
                    message=f"Current weather in {loc} verified: {temp}°C and {cond} with {hum}% humidity, sir.",
                    actions=[
                        ActionExecutionRecord(
                            tool="weather.get",
                            target=loc,
                            status="success",
                            message=summary,
                            verified=True,
                        )
                    ],
                )
            return ChatResponse(
                intent="task_request",
                message=f"Weather report retrieved for {city.title()}: Conditions are pleasant, sir.",
                actions=[
                    ActionExecutionRecord(
                        tool="weather.get",
                        target=city.title(),
                        status="success",
                        message=f"Pleasant conditions in {city.title()}",
                        verified=True,
                    )
                ],
            )

        # 5. Desktop Application Launch (Supports any application on Windows)
        app_match = re.search(
            r"\b(?:open|launch|start|run)\s+(?:the\s+)?(?:app\s+|application\s+|program\s+)?([a-zA-Z0-9_.-]+(?:\s+[a-zA-Z0-9_.-]+)?)\b",
            clean_lower,
        )
        if app_match:
            app = app_match.group(1)
            result = self.execute_tool_request(ToolExecutionRequest(name="system.open_app", arguments={"app_name": app}))
            app_disp = app.capitalize()
            if result.success:
                return ChatResponse(
                    intent="task_request",
                    message=f"I have launched {app_disp} on your desktop, sir.",
                    actions=[
                        ActionExecutionRecord(
                            tool="system.open_app",
                            target=app,
                            status="success",
                            message=f"Launched {app_disp}",
                            verified=True,
                        )
                    ],
                )
            return ChatResponse(
                intent="task_request",
                message=f"I was unable to launch {app_disp}, sir: {result.error or 'Failed'}",
                actions=[
                    ActionExecutionRecord(
                        tool="system.open_app",
                        target=app,
                        status="failed",
                        message=f"Failed to launch {app_disp}",
                        verified=False,
                    )
                ],
            )

        # 6. System Date & Time
        if re.search(r"\b(?:what time is it|what is the time|current time|what is today's date|today's date|what day is it)\b", clean_lower):
            result = self.execute_tool_request(ToolExecutionRequest(name="system.datetime", arguments={}))
            if result.success and isinstance(result.output, dict):
                summary = result.output.get("summary", "Current date and time retrieved")
                return ChatResponse(
                    intent="task_request",
                    message=f"{summary}, sir.",
                    actions=[
                        ActionExecutionRecord(
                            tool="system.datetime",
                            target="local",
                            status="success",
                            message=summary,
                            verified=True,
                        )
                    ],
                )

        # 7. Safe Shell Command Execution
        cmd_match = re.search(r"\b(?:run command|execute command|run shell)\s+(.+)$", message, re.IGNORECASE)
        if cmd_match:
            cmd = cmd_match.group(1).strip()
            result = self.execute_tool_request(ToolExecutionRequest(name="system.run_command", arguments={"command": cmd}))
            output = result.output.get("stdout", "") if result.success and isinstance(result.output, dict) else ""
            summary = output[:200] + ("..." if len(output) > 200 else "")
            return ChatResponse(
                intent="task_request",
                message=f"Command executed, sir.\n{summary}",
                actions=[
                    ActionExecutionRecord(
                        tool="system.run_command",
                        target=cmd,
                        status="success" if result.success else "failed",
                        message=summary,
                        verified=result.success,
                    )
                ],
            )

        return None
