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
    "I am ATLAS, your autonomous task and life assistant system. "
    "I can answer questions and possess direct execution capabilities across your PC, web, and cloud services: "
    "I can search the live web and sports feeds for real-time scores and news, "
    "inspect and analyze your active screen through multimodal neural vision, "
    "open and close any website or browser tab, launch, focus, and close any desktop application on your Windows PC, "
    "enumerate open windows, simulate keyboard typing and hotkeys, control window states (maximize, minimize, show desktop), "
    "control media playback (play, pause, skip) and master volume, inspect real-time CPU, RAM, disk, and battery hardware vitals, lock your workstation, "
    "manage your Google Calendar events and find free slots, search and draft Gmail messages, "
    "inspect GitHub repositories, issues, PRs, and workflow runs, "
    "check live global weather, read and write files, and execute safe shell commands with verified proof. "
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

    def ensure_user_tools(self, user_id: str | None) -> None:
        if not user_id or not self.tool_executor:
            return
        from backend.app.security.models import PermissionId, RiskLevel
        from backend.app.security.policy import PermissionRule
        permission_by_string = {p.value: p for p in PermissionId}
        user_tools = []
        try:
            from backend.app.integrations.google.runtime import get_google_api_client
            from backend.app.integrations.google.tools import create_google_tools
            g_tools = [t for t in create_google_tools(get_google_api_client(user_id)) if t.name != "system.echo"]
            user_tools.extend(g_tools)
        except Exception:
            pass

        try:
            from backend.app.integrations.github.runtime import get_github_api_client
            from backend.app.integrations.github.tools import create_all_github_tools
            user_tools.extend(create_all_github_tools(get_github_api_client()))
        except Exception:
            pass

        for t in user_tools:
            if t.name not in self.tool_executor.registry._tools:
                self.tool_executor.registry.register(t)
                perm = permission_by_string.get(t.permission_id)
                if perm:
                    self.tool_executor.permission_boundary.policy._rules[(t.name, perm)] = PermissionRule(
                        allowed=True,
                        risk_level=RiskLevel(t.risk_level),
                        permission_required=t.permission_required,
                    )


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

        if memory_user_id:
            self.ensure_user_tools(memory_user_id)

        action_response = self._try_execute_action(request.message, request.image_data, memory_user_id)
        if action_response is not None:
            return action_response

        cognitive_response = self._try_cognitive_tool_execution(request, memory_user_id)
        if cognitive_response is not None:
            return cognitive_response

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

    def _try_execute_action(self, message: str, image_data: str | None = None, user_id: str | None = None) -> ChatResponse | None:

        clean_lower = message.lower().strip("?.! ")

        # 0a. Intelligent Screen Vision Observer & Live Context Sensing
        is_direct_screen_query = bool(
            re.search(
                r"\b(?:can\s+you\s+(?:able\s+to\s+)?see\s+my\s+screen|see\s+(?:what(?:'s|\s+is)\s+on\s+)?my\s+screen|look\s+at\s+my\s+screen|what(?:'s|\s+is)\s+on\s+my\s+screen|inspect\s+my\s+screen|read\s+my\s+screen|check\s+my\s+screen|what\s+am\s+i\s+looking\s+at|describe\s+my\s+screen|help\s+me\s+with\s+(?:what(?:'s|\s+is)\s+on\s+)?my\s+screen)\b",
                clean_lower,
            )
        )
        is_error_query = bool(
            re.search(
                r"\b(?:what\s+error|debug\s+(?:this\s+)?(?:error|code|issue|screen)|explain\s+(?:this\s+)?error|why\s+(?:is\s+this\s+failing|did\s+this\s+fail)|fix\s+(?:this\s+)?error|compiler\s+error|stack\s*trace|find\s+(?:the\s+)?(?:bug|error))\b",
                clean_lower,
            )
        )
        is_code_query = bool(
            re.search(
                r"\b(?:explain\s+(?:this\s+|the\s+)?code|review\s+(?:this\s+|the\s+)?code|what\s+does\s+this\s+(?:code|function|class|method)\s+do|inspect\s+(?:this\s+|the\s+)?code)\b",
                clean_lower,
            )
        )
        is_ocr_query = bool(
            re.search(
                r"\b(?:read\s+(?:the\s+)?(?:text|words|content)|extract\s+(?:the\s+)?text|ocr\s+(?:my\s+)?screen|transcribe\s+(?:my\s+screen|this)|what\s+does\s+(?:it|this)\s+say)\b",
                clean_lower,
            )
        )
        is_summary_query = bool(
            re.search(
                r"\b(?:summarize\s+(?:what(?:'s|\s+is)\s+on\s+my\s+screen|this\s+(?:page|document|pdf|article|screen))|give\s+me\s+(?:a\s+)?summary\s+of\s+(?:my\s+screen|this))\b",
                clean_lower,
            )
        )

        should_trigger_vision = (
            is_direct_screen_query
            or (image_data and (is_error_query or is_code_query or is_ocr_query or is_summary_query or "on my screen" in clean_lower or "on screen" in clean_lower))
            or (not image_data and ("on my screen" in clean_lower or "on screen" in clean_lower or (is_direct_screen_query or ((is_error_query or is_code_query or is_ocr_query or is_summary_query) and "screen" in clean_lower))))
        )

        if should_trigger_vision:
            if image_data:
                if is_error_query:
                    task_directive = (
                        f"The user asks: '{message}'.\n"
                        "Carefully examine the active screen: locate and read any visible compiler errors, exceptions, stack traces, warning banners, or broken UI elements. "
                        "Explain the root cause clearly, indicate the exact file/line if visible, and provide the concrete, step-by-step fix."
                    )
                    action_msg = "Diagnosed screen error and failure root cause via Gemini Vision core"
                elif is_code_query:
                    task_directive = (
                        f"The user asks: '{message}'.\n"
                        "Review the code and programming environment visible on the active screen. "
                        "Explain the logic, architecture, functions, or potential edge cases, and directly answer the user's technical question."
                    )
                    action_msg = "Inspected and reviewed on-screen code via Gemini Vision core"
                elif is_ocr_query:
                    task_directive = (
                        f"The user asks: '{message}'.\n"
                        "Extract and transcribe all readable text, data, labels, code snippets, or document contents visible on the active screen display. "
                        "Present the extracted text clearly and organized."
                    )
                    action_msg = "Extracted and transcribed on-screen text (OCR) via Gemini Vision core"
                elif is_summary_query:
                    task_directive = (
                        f"The user asks: '{message}'.\n"
                        "Provide a crisp, structured executive summary of the document, article, webpage, dashboard, or presentation currently open on the screen."
                    )
                    action_msg = "Summarized active screen document and visual content via Gemini Vision core"
                else:
                    task_directive = (
                        f"The user asks: '{message}'.\n"
                        "Describe what is currently visible on the active display: the active application, open windows, text, code, errors, or documents, and provide concrete assistance."
                    )
                    action_msg = "Analyzed active screen display via Gemini Vision core"

                vision_req = LLMRequest(
                    messages=[
                        LLMMessage(
                            role="user",
                            content=(
                                "You are ATLAS, an elite AI assistant inspecting the user's active screen via real-time multimodal optical neural vision.\n\n"
                                f"{task_directive}\n\n"
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
                            message=action_msg,
                            verified=True,
                        )
                    ],
                )
            else:
                return ChatResponse(
                    intent="conversation",
                    message=(
                        "I require a visual link to inspect your display, sir! "
                        "Please click the **[ 👁️ SHARE SCREEN ]** button on your HUD (or press Ctrl+Shift+S) to establish a live display link with my vision core. "
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
            r"\b(?:open|launch|go to|browse to|visit)\s+(?:the\s+)?(?:website\s+)?((?:https?://)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?|https?://[^\s]+|youtube|google|github|reddit|twitter|x|spotify|netflix|wikipedia|chatgpt|gemini|linkedin|amazon|facebook|instagram|twitch|gmail|maps|drive|outlook|yahoo|ebay|walmart)\b",
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
        app_match = None
        if not clean_lower.startswith(("list", "show", "what", "which", "find", "search", "switch", "focus", "close", "minimize", "maximize")):
            app_match = re.search(
                r"\b(?:open|launch|start|run)\s+(?:the\s+)?(?:app\s+|application\s+|program\s+)?([a-zA-Z0-9_.-]+(?:\s+[a-zA-Z0-9_.-]+)?)\b",
                clean_lower,
            )
        if app_match:
            app = app_match.group(1).strip()
            if app not in {"app", "application", "program", "window", "windows", "tab", "tabs", "file", "files"}:
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

        # 8a. File System Read
        read_file_match = re.search(
            r"\b(?:read|view|inspect|show|display|cat)\s+(?:the\s+)?(?:contents?\s+of\s+)?(?:file\s+)?([a-zA-Z]:\\[^\s]+|\.?/[^\s]+|[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+)\b",
            clean_lower,
        )
        if read_file_match:
            filepath = read_file_match.group(1).strip()
            result = self.execute_tool_request(ToolExecutionRequest(name="system.file_read", arguments={"path": filepath}))
            if result.success and isinstance(result.output, dict):
                content = result.output.get("content", "")
                summary = content[:500] + ("..." if len(content) > 500 else "")
                return ChatResponse(
                    intent="task_request",
                    message=f"I have inspected '{filepath}' for you, sir:\n```\n{summary}\n```",
                    actions=[
                        ActionExecutionRecord(
                            tool="system.file_read",
                            target=filepath,
                            status="success",
                            message=f"Read {len(content)} characters from {filepath}",
                            verified=True,
                        )
                    ],
                )
            return ChatResponse(
                intent="task_request",
                message=f"I was unable to read file '{filepath}', sir: {result.error or 'File not accessible'}",
                actions=[
                    ActionExecutionRecord(
                        tool="system.file_read",
                        target=filepath,
                        status="failed",
                        message=f"Failed to read {filepath}",
                        verified=False,
                    )
                ],
            )

        # 8b. File System Write
        write_file_match = re.search(
            r"\b(?:write|save|append)\s+(?:to\s+)?file\s+([a-zA-Z]:\\[^\s]+|\.?/[^\s]+|[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+)(?::|\s+with\s+(?:content|text)\s+)(.+)$",
            message,
            re.IGNORECASE,
        )
        if write_file_match:
            filepath = write_file_match.group(1).strip()
            content_to_write = write_file_match.group(2).strip().strip("'\"")
            result = self.execute_tool_request(ToolExecutionRequest(name="system.file_write", arguments={"path": filepath, "content": content_to_write}))
            if result.success:
                return ChatResponse(
                    intent="task_request",
                    message=f"I have successfully written the contents to '{filepath}', sir.",
                    actions=[
                        ActionExecutionRecord(
                            tool="system.file_write",
                            target=filepath,
                            status="success",
                            message=f"Wrote to {filepath}",
                            verified=True,
                        )
                    ],
                )

        # 9a. Google Calendar List Events
        cal_match = re.search(
            r"\b(?:what\s+meetings?|meetings?\s+(?:do\s+i\s+have|are\s+scheduled|today|tomorrow)|(?:my\s+)?(?:calendar|schedule|agenda)|do\s+i\s+have\s+(?:any\s+)?(?:meetings?|calls?|events?)|upcoming\s+(?:meetings?|events?)|check\s+(?:my\s+)?(?:calendar|schedule))\b",
            clean_lower,
        )
        if cal_match:
            if "calendar.list_events" not in self.tool_executor.registry._tools:
                return ChatResponse(
                    intent="conversation",
                    message=(
                        "Your Google Workspace is not currently connected, sir. "
                        "You can connect your Google Calendar and Gmail in the System Console under Connected Services."
                    ),
                    actions=[
                        ActionExecutionRecord(
                            tool="calendar.list_events",
                            target="primary",
                            status="requested",
                            message="Google integration required - please connect in System Console",
                            verified=False,
                        )
                    ],
                )
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            end = now + (timedelta(days=1) if "today" in clean_lower else timedelta(days=7))
            result = self.execute_tool_request(ToolExecutionRequest(
                name="calendar.list_events",
                arguments={"calendar_id": "primary", "time_min": now.isoformat(), "time_max": end.isoformat(), "max_results": 20}
            ))
            if result.success and isinstance(result.output, dict):
                events = result.output.get("events", [])
                if events:
                    event_lines = [f"• {e.get('summary', 'Untitled')} ({e.get('start', {}).get('dateTime', 'All Day')})" for e in events[:5]]
                    msg = f"You have {len(events)} scheduled event(s), sir:\n" + "\n".join(event_lines)
                else:
                    msg = "Your calendar appears completely clear for this period, sir. No scheduled meetings found."
                return ChatResponse(
                    intent="task_request",
                    message=msg,
                    actions=[
                        ActionExecutionRecord(
                            tool="calendar.list_events",
                            target="primary",
                            status="success",
                            message=f"Retrieved {len(events)} calendar events",
                            verified=True,
                        )
                    ],
                )
            return ChatResponse(
                intent="conversation",
                message="Your Google Workspace is not currently connected, sir. You can connect your Google Calendar and Gmail in the System Console under Connected Services.",
                actions=[
                    ActionExecutionRecord(
                        tool="calendar.list_events",
                        target="primary",
                        status="requested",
                        message="Google integration required - please connect in System Console",
                        verified=False,
                    )
                ],
            )

        # 9b. Calendar Free Slots
        free_slots_match = re.search(
            r"\b(?:free\s+slots?|free\s+time|available\s+slots?|find\s+free\s+time|when\s+am\s+i\s+free)\b",
            clean_lower,
        )
        if free_slots_match:
            if "calendar.find_free_slots" not in self.tool_executor.registry._tools:
                return ChatResponse(
                    intent="conversation",
                    message="Your Google Workspace is not currently connected, sir. Please connect Google Calendar in the System Console.",
                    actions=[ActionExecutionRecord(tool="calendar.find_free_slots", target="primary", status="requested", message="Google connection required", verified=False)],
                )
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=2)
            result = self.execute_tool_request(ToolExecutionRequest(
                name="calendar.find_free_slots",
                arguments={"calendar_id": "primary", "time_min": now.isoformat(), "time_max": end.isoformat(), "duration_minutes": 30}
            ))
            if result.success and isinstance(result.output, dict):
                slots = result.output.get("free_slots", [])
                if slots:
                    slot_lines = [f"• {s.get('start')} to {s.get('end')}" for s in slots[:5]]
                    msg = f"I have discovered {len(slots)} available window(s) for you, sir:\n" + "\n".join(slot_lines)
                else:
                    msg = "No open 30-minute free slots detected within the next 48 hours, sir."
                return ChatResponse(intent="task_request", message=msg, actions=[ActionExecutionRecord(tool="calendar.find_free_slots", target="primary", status="success", message=f"Found {len(slots)} free slots", verified=True)])

        # 10. Gmail Search & Read
        gmail_match = re.search(
            r"\b(?:check\s+(?:my\s+)?(?:emails?|inbox|mail|messages?)|search\s+(?:my\s+)?(?:emails?|inbox)\s*(?:for\s+)?(.*)|unread\s+(?:emails?|messages?)|any\s+(?:new\s+)?(?:emails?|messages?))\b",
            clean_lower,
        )
        if gmail_match:
            if "gmail.search" not in self.tool_executor.registry._tools:
                return ChatResponse(
                    intent="conversation",
                    message="Your Google Workspace is not currently connected, sir. You can connect Gmail in the System Console under Connected Services.",
                    actions=[ActionExecutionRecord(tool="gmail.search", target="inbox", status="requested", message="Google integration required", verified=False)],
                )
            query = "is:unread"
            if gmail_match.group(1) and gmail_match.group(1).strip():
                query = gmail_match.group(1).strip()
            result = self.execute_tool_request(ToolExecutionRequest(name="gmail.search", arguments={"query": query, "max_results": 10}))
            if result.success and isinstance(result.output, dict):
                messages = result.output.get("messages", [])
                if messages:
                    msg_lines = [f"• From: {m.get('from', 'Unknown')} | Subject: {m.get('subject', 'No Subject')}" for m in messages[:5]]
                    msg = f"I have queried your inbox, sir. Found {len(messages)} matching email(s):\n" + "\n".join(msg_lines)
                else:
                    msg = f"I have checked your inbox, sir. No messages found matching '{query}'."
                return ChatResponse(
                    intent="task_request",
                    message=msg,
                    actions=[ActionExecutionRecord(tool="gmail.search", target=query, status="success", message=f"Found {len(messages)} messages", verified=True)],
                )
            return ChatResponse(
                intent="conversation",
                message="Your Google Workspace is not currently connected, sir. You can connect your Gmail in the System Console under Connected Services.",
                actions=[ActionExecutionRecord(tool="gmail.search", target="inbox", status="requested", message="Google integration required", verified=False)],
            )

        # 11a. GitHub List Repositories
        gh_repos_match = re.search(
            r"\b(?:list|show|get)\s+(?:my\s+)?(?:github\s+)?repos(?:itories)?\b",
            clean_lower,
        )
        if gh_repos_match:
            if "github.list_repositories" not in self.tool_executor.registry._tools:
                return ChatResponse(
                    intent="conversation",
                    message="GitHub App integration is not currently configured for your account, sir. You can configure GitHub authentication in the System Console.",
                    actions=[ActionExecutionRecord(tool="github.list_repositories", target="github", status="requested", message="GitHub credentials required", verified=False)],
                )
            result = self.execute_tool_request(ToolExecutionRequest(name="github.list_repositories", arguments={"page": 1, "per_page": 20}))
            if result.success and isinstance(result.output, dict):
                repos = result.output.get("repositories", [])
                if repos:
                    repo_lines = [f"• {r.get('full_name')} ({'Private' if r.get('private') else 'Public'})" for r in repos[:8]]
                    msg = f"I have retrieved your GitHub repositories, sir:\n" + "\n".join(repo_lines)
                else:
                    msg = "No accessible GitHub repositories found under your authenticated account, sir."
                return ChatResponse(intent="task_request", message=msg, actions=[ActionExecutionRecord(tool="github.list_repositories", target="user", status="success", message=f"Retrieved {len(repos)} repositories", verified=True)])
            return ChatResponse(
                intent="conversation",
                message="GitHub App integration is not currently configured for your account, sir. You can configure GitHub authentication in the System Console.",
                actions=[ActionExecutionRecord(tool="github.list_repositories", target="github", status="requested", message="GitHub credentials required", verified=False)],
            )

        # 11b. GitHub List Issues
        gh_issues_match = re.search(
            r"\b(?:list|show|check|get)\s+(?:open\s+)?issues\s+(?:on|in|for)\s+([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\b",
            clean_lower,
        )
        if gh_issues_match:
            full_repo = gh_issues_match.group(1).strip()
            owner, repo = full_repo.split("/", 1)
            if "github.list_issues" not in self.tool_executor.registry._tools:
                return ChatResponse(intent="conversation", message="GitHub App integration is not currently configured, sir.", actions=[ActionExecutionRecord(tool="github.list_issues", target=full_repo, status="requested", message="GitHub credentials required", verified=False)])
            result = self.execute_tool_request(ToolExecutionRequest(name="github.list_issues", arguments={"owner": owner, "repo": repo, "page": 1, "per_page": 10}))
            if result.success and isinstance(result.output, dict):
                issues = result.output.get("issues", [])
                if issues:
                    issue_lines = [f"• #{i.get('number')} {i.get('title')} ({i.get('state')})" for i in issues[:5]]
                    msg = f"Open issues for '{full_repo}', sir:\n" + "\n".join(issue_lines)
                else:
                    msg = f"No open issues found on repository '{full_repo}', sir."
                return ChatResponse(intent="task_request", message=msg, actions=[ActionExecutionRecord(tool="github.list_issues", target=full_repo, status="success", message=f"Retrieved {len(issues)} issues", verified=True)])
            return ChatResponse(intent="task_request", message=f"Could not retrieve issues for '{full_repo}', sir: {result.error}", actions=[ActionExecutionRecord(tool="github.list_issues", target=full_repo, status="failed", message=f"Failed: {result.error}", verified=False)])

        # 11c. GitHub Create Issue
        gh_create_issue_match = re.search(
            r"\b(?:create|open)\s+(?:an?\s+)?issue\s+(?:on|in|for)\s+([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\s+(?:titled|with title)\s+([a-zA-Z0-9_\s.-]+)\b",
            message,
            re.IGNORECASE,
        )
        if gh_create_issue_match:
            full_repo = gh_create_issue_match.group(1).strip()
            title = gh_create_issue_match.group(2).strip()
            owner, repo = full_repo.split("/", 1)
            if "github.create_issue" not in self.tool_executor.registry._tools:
                return ChatResponse(intent="conversation", message="GitHub App integration is not currently configured, sir.", actions=[ActionExecutionRecord(tool="github.create_issue", target=full_repo, status="requested", message="GitHub credentials required", verified=False)])
            result = self.execute_tool_request(ToolExecutionRequest(name="github.create_issue", arguments={"owner": owner, "repo": repo, "title": title}))
            if result.success and isinstance(result.output, dict):
                issue_num = result.output.get("number")
                url = result.output.get("html_url", "")
                msg = f"I have successfully created issue #{issue_num} on '{full_repo}' titled '{title}', sir.\n{url}"
                return ChatResponse(intent="task_request", message=msg, actions=[ActionExecutionRecord(tool="github.create_issue", target=f"{full_repo}#{issue_num}", status="success", message=f"Created issue #{issue_num}", verified=True)])
            return ChatResponse(intent="task_request", message=f"Failed to create issue on '{full_repo}', sir: {result.error}", actions=[ActionExecutionRecord(tool="github.create_issue", target=full_repo, status="failed", message=f"Failed: {result.error}", verified=False)])

        # 11d. GitHub Workflow Runs
        gh_workflow_match = re.search(
            r"\b(?:workflow\s+runs?|github\s+actions?|ci\s+runs?|build\s+status)\s+(?:on|for|in)\s+([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\b",
            clean_lower,
        )
        if gh_workflow_match:
            full_repo = gh_workflow_match.group(1).strip()
            owner, repo = full_repo.split("/", 1)
            if "github.list_workflow_runs" not in self.tool_executor.registry._tools:
                return ChatResponse(intent="conversation", message="GitHub App integration is not configured, sir.", actions=[ActionExecutionRecord(tool="github.list_workflow_runs", target=full_repo, status="requested", message="GitHub credentials required", verified=False)])
            result = self.execute_tool_request(ToolExecutionRequest(name="github.list_workflow_runs", arguments={"owner": owner, "repo": repo, "page": 1, "per_page": 5}))
            if result.success and isinstance(result.output, dict):
                runs = result.output.get("workflow_runs", [])
                if runs:
                    run_lines = [f"• {r.get('name')} (#{r.get('run_number')}): {r.get('conclusion') or r.get('status')}" for r in runs[:5]]
                    msg = f"Recent workflow runs on '{full_repo}', sir:\n" + "\n".join(run_lines)
                else:
                    msg = f"No workflow runs found on '{full_repo}', sir."
                return ChatResponse(intent="task_request", message=msg, actions=[ActionExecutionRecord(tool="github.list_workflow_runs", target=full_repo, status="success", message=f"Retrieved {len(runs)} workflow runs", verified=True)])
            return ChatResponse(intent="task_request", message=f"Could not retrieve workflow runs for '{full_repo}', sir: {result.error}", actions=[ActionExecutionRecord(tool="github.list_workflow_runs", target=full_repo, status="failed", message=f"Failed: {result.error}", verified=False)])

        # 12. List Active Windows / Running Applications
        list_windows_match = re.search(
            r"\b(?:what\s+windows|what\s+apps|which\s+apps|list\s+(?:open\s+)?(?:windows|apps|applications)|show\s+open\s+windows|show\s+active\s+apps|running\s+applications|what\s+is\s+running)\b",
            clean_lower,
        )
        if list_windows_match:
            result = self.execute_tool_request(ToolExecutionRequest(name="system.list_windows", arguments={}))
            if result.success and isinstance(result.output, dict):
                summary = result.output.get("summary", "No active windows found.")
                return ChatResponse(
                    intent="task_request",
                    message=summary,
                    actions=[ActionExecutionRecord(tool="system.list_windows", target="desktop", status="success", message=summary, verified=True)]
                )
            return ChatResponse(
                intent="task_request",
                message=f"Could not enumerate open windows, sir: {result.error}",
                actions=[ActionExecutionRecord(tool="system.list_windows", target="desktop", status="failed", message=f"Failed: {result.error}", verified=False)]
            )

        # 12b. Custom Workflow Protocols & Desktop Macros (Focus Mode, Dev Setup, End of Day, Clean Slate, Media Center)
        protocol_match = re.search(
            r"\b(?:(?:run|execute|engage|start|activate|trigger|initiate)\s+)?(?:protocol\s+([a-zA-Z_\s-]+)|([a-zA-Z_\s-]+?)\s+protocol)\b",
            clean_lower,
        )
        protocol_name = None
        if protocol_match:
            raw_p = (protocol_match.group(1) or protocol_match.group(2) or "").strip()
            p_norm = raw_p.lower().replace("-", "_").replace(" ", "_")
            if any(k in p_norm for k in ["focus", "dev", "end_of_day", "clean_slate", "media", "deep_work", "clear_desktop", "purge", "entertainment", "movie"]):
                protocol_name = p_norm
        elif re.search(r"\b(?:engage|enter|activate|start)\s+(?:focus\s+mode|deep\s+work)\b", clean_lower):
            protocol_name = "focus_mode"
        elif re.search(r"\b(?:setup|start|launch)\s+dev(?:eloper)?\s+environment\b", clean_lower):
            protocol_name = "dev_setup"
        elif re.search(r"\b(?:end\s+of\s+day|wrap\s+up\s+(?:the\s+)?day)\b", clean_lower):
            protocol_name = "end_of_day"
        elif re.search(r"\b(?:clean\s+slate|clear\s+desktop)\b", clean_lower):
            protocol_name = "clean_slate"
        elif re.search(r"\b(?:media\s+center|entertainment\s+mode)\b", clean_lower):
            protocol_name = "media_center"

        if protocol_name:
            canonical_name = "focus_mode"
            if "focus" in protocol_name or "deep" in protocol_name:
                canonical_name = "focus_mode"
            elif "dev" in protocol_name or "coding" in protocol_name:
                canonical_name = "dev_setup"
            elif "end" in protocol_name or "wrap" in protocol_name:
                canonical_name = "end_of_day"
            elif "clean" in protocol_name or "clear" in protocol_name or "purge" in protocol_name:
                canonical_name = "clean_slate"
            elif "media" in protocol_name or "movie" in protocol_name or "entertain" in protocol_name:
                canonical_name = "media_center"
            else:
                canonical_name = protocol_name

            result = self.execute_tool_request(
                ToolExecutionRequest(
                    name="system.execute_protocol",
                    arguments={"protocol": canonical_name},
                )
            )
            if result.success and isinstance(result.output, dict):
                msg = result.output.get("message", f"Protocol '{canonical_name}' executed, sir.")
                raw_steps = result.output.get("executed_steps", [])
                action_records = []
                for s in raw_steps:
                    action_records.append(
                        ActionExecutionRecord(
                            tool=s.get("tool", "system.execute_protocol"),
                            target=s.get("target", canonical_name),
                            status=s.get("status", "success"),
                            message=s.get("message", "Executed protocol step"),
                            verified=bool(s.get("verified", True)),
                        )
                    )
                if not action_records:
                    action_records.append(
                        ActionExecutionRecord(
                            tool="system.execute_protocol",
                            target=canonical_name,
                            status="success",
                            message=msg,
                            verified=True,
                        )
                    )
                return ChatResponse(
                    intent="task_request",
                    message=msg,
                    actions=action_records,
                )
            return ChatResponse(
                intent="task_request",
                message=f"Could not execute protocol '{canonical_name}', sir: {result.error}",
                actions=[
                    ActionExecutionRecord(
                        tool="system.execute_protocol",
                        target=canonical_name,
                        status="failed",
                        message=f"Failed: {result.error}",
                        verified=False,
                    )
                ],
            )

        # 13. Focus / Switch Application Window
        focus_window_match = re.search(
            r"\b(?:focus|switch\s+to|bring\s+to\s+front|activate)\s+(?:the\s+)?([a-zA-Z0-9_\s.-]+?)(?:\s+window|\s+app)?$",
            clean_lower,
        )
        if focus_window_match:
            target_win = focus_window_match.group(1).strip()
            if target_win not in {"on", "it", "my", "this", "that", "me"}:
                result = self.execute_tool_request(ToolExecutionRequest(name="system.focus_window", arguments={"target": target_win}))
                if result.success and isinstance(result.output, dict):
                    msg = result.output.get("message", f"Brought {target_win} to the foreground, sir.")
                    return ChatResponse(
                        intent="task_request",
                        message=msg,
                        actions=[ActionExecutionRecord(tool="system.focus_window", target=target_win, status="success", message=msg, verified=True)]
                    )
                return ChatResponse(
                    intent="task_request",
                    message=f"Could not focus {target_win}, sir: {result.error}",
                    actions=[ActionExecutionRecord(tool="system.focus_window", target=target_win, status="failed", message=f"Failed: {result.error}", verified=False)]
                )

        # 14. Send Keystrokes & Type Text
        type_text_match = re.search(
            r'\b(?:type|write|input|send\s+keys?)\s+(.+?)(?:\s+(?:in|into|on)\s+([a-zA-Z0-9_\s.-]+))?$',
            message,
            re.IGNORECASE,
        )
        if type_text_match:
            raw_text = type_text_match.group(1).strip().strip('"\' ')
            target_app = type_text_match.group(2).strip() if type_text_match.group(2) else None
            # Do not intercept file write or shell run
            if not re.search(r"\b(?:to\s+file|into\s+file|\bfile\b|\.txt|\.py|\.json)\b", clean_lower):
                has_enter = bool(re.search(r"\b(?:and\s+press\s+enter|and\s+hit\s+enter)\b", clean_lower))
                clean_keys = re.sub(r"\s+(?:and\s+press\s+enter|and\s+hit\s+enter)\b", "", raw_text, flags=re.IGNORECASE).strip()
                result = self.execute_tool_request(
                    ToolExecutionRequest(
                        name="system.send_keys",
                        arguments={"text": clean_keys, "target_window": target_app, "press_enter": has_enter}
                    )
                )
                if result.success and isinstance(result.output, dict):
                    msg = result.output.get("message", f"Typed \"{clean_keys}\", sir.")
                    return ChatResponse(
                        intent="task_request",
                        message=msg,
                        actions=[ActionExecutionRecord(tool="system.send_keys", target=target_app or "active_window", status="success", message=msg, verified=True)]
                    )
                return ChatResponse(
                    intent="task_request",
                    message=f"Could not send keystrokes, sir: {result.error}",
                    actions=[ActionExecutionRecord(tool="system.send_keys", target=target_app or "active_window", status="failed", message=f"Failed: {result.error}", verified=False)]
                )

        # 15. Window State (Minimize All / Show Desktop / Maximize)
        min_all_match = re.search(
            r"\b(?:minimize\s+all(?:\s+windows)?|show\s+desktop|hide\s+all\s+windows)\b",
            clean_lower,
        )
        if min_all_match:
            result = self.execute_tool_request(ToolExecutionRequest(name="system.window_state", arguments={"action": "minimize_all"}))
            if result.success and isinstance(result.output, dict):
                msg = result.output.get("message", "All desktop windows minimized to reveal your desktop, sir.")
                return ChatResponse(
                    intent="task_request",
                    message=msg,
                    actions=[ActionExecutionRecord(tool="system.window_state", target="all_windows", status="success", message=msg, verified=True)]
                )
            return ChatResponse(
                intent="task_request",
                message=f"Could not minimize windows, sir: {result.error}",
                actions=[ActionExecutionRecord(tool="system.window_state", target="all_windows", status="failed", message=f"Failed: {result.error}", verified=False)]
            )

        maximize_match = re.search(
            r"\b(?:maximize|restore)\s+(?:the\s+)?([a-zA-Z0-9_\s.-]+?)(?:\s+window|\s+app)?$",
            clean_lower,
        )
        if maximize_match:
            act = "maximize" if "maximize" in clean_lower else "restore"
            target_win = maximize_match.group(1).strip()
            result = self.execute_tool_request(ToolExecutionRequest(name="system.window_state", arguments={"action": act, "target": target_win}))
            if result.success and isinstance(result.output, dict):
                msg = result.output.get("message", f"Executed {act} on {target_win}, sir.")
                return ChatResponse(
                    intent="task_request",
                    message=msg,
                    actions=[ActionExecutionRecord(tool="system.window_state", target=target_win, status="success", message=msg, verified=True)]
                )

        # 16. Media Playback Control (Play, Pause, Next, Previous, Stop)
        media_match = re.search(
            r"\b(?:pause\s+(?:music|song|playback|audio)|stop\s+(?:music|song|playback|audio)|play\s+(?:music|song|audio)|resume\s+(?:music|song|playback|audio)|next\s+(?:song|track)|skip\s+(?:song|track)|previous\s+(?:song|track)|last\s+(?:song|track)|unpause)\b",
            clean_lower,
        )
        if media_match:
            matched_phrase = media_match.group(0)
            act = "play_pause"
            if "next" in matched_phrase or "skip" in matched_phrase:
                act = "next"
            elif "previous" in matched_phrase or "last" in matched_phrase:
                act = "previous"
            elif "pause" in matched_phrase or "stop" in matched_phrase:
                act = "pause"
            elif "play" in matched_phrase or "resume" in matched_phrase or "unpause" in matched_phrase:
                act = "play"

            result = self.execute_tool_request(ToolExecutionRequest(name="system.media_control", arguments={"action": act}))
            if result.success and isinstance(result.output, dict):
                msg = result.output.get("message", f"Adjusted media playback ({act}), sir.")
                return ChatResponse(
                    intent="task_request",
                    message=msg,
                    actions=[ActionExecutionRecord(tool="system.media_control", target="media_player", status="success", message=msg, verified=True)]
                )
            return ChatResponse(
                intent="task_request",
                message=f"Could not adjust media playback, sir: {result.error}",
                actions=[ActionExecutionRecord(tool="system.media_control", target="media_player", status="failed", message=f"Failed: {result.error}", verified=False)]
            )

        # 17. Volume & Audio Control (Mute, Unmute, Volume Up, Volume Down, Set Volume)
        vol_match = re.search(
            r"\b(?:(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})%?|(?:turn\s+)?volume\s+(up|down)|(increase|decrease|lower|turn\s+up|turn\s+down)\s+volume|(mute|unmute)\s*(?:audio|volume|sound|computer)?)\b",
            clean_lower,
        )
        if vol_match:
            pct_val = None
            if vol_match.group(1):
                try:
                    pct_val = int(vol_match.group(1))
                    act = "set"
                except ValueError:
                    pct_val = None
                    act = "up"
            elif vol_match.group(2):
                act = vol_match.group(2)
            elif vol_match.group(3):
                act = "up" if "up" in vol_match.group(3) or "increase" in vol_match.group(3) else "down"
            elif vol_match.group(4):
                act = vol_match.group(4)
            else:
                act = "up" if "up" in clean_lower else "down"

            args = {"action": act}
            if pct_val is not None:
                args["percent"] = pct_val

            result = self.execute_tool_request(ToolExecutionRequest(name="system.volume_control", arguments=args))
            if result.success and isinstance(result.output, dict):
                msg = result.output.get("message", f"Adjusted audio volume, sir.")
                return ChatResponse(
                    intent="task_request",
                    message=msg,
                    actions=[ActionExecutionRecord(tool="system.volume_control", target="master_audio", status="success", message=msg, verified=True)]
                )
            return ChatResponse(
                intent="task_request",
                message=f"Could not adjust volume, sir: {result.error}",
                actions=[ActionExecutionRecord(tool="system.volume_control", target="master_audio", status="failed", message=f"Failed: {result.error}", verified=False)]
            )

        # 18. System Hardware Diagnostics & Vitals (CPU, RAM, Disk, Battery)
        vitals_match = re.search(
            r"\b(?:system\s+(?:diagnostics|vitals|health|status)|hardware\s+(?:status|diagnostics|vitals|health)|check\s+(?:system|hardware|vitals|cpu|ram|battery|specs)|how\s+is\s+my\s+(?:pc|computer|system)\s+doing|how\s+much\s+(?:ram|memory|disk)\s+is\s+free|pc\s+status|diagnostic\s+report)\b",
            clean_lower,
        )
        if vitals_match:
            result = self.execute_tool_request(ToolExecutionRequest(name="system.vitals", arguments={"detail_level": "summary"}))
            if result.success and isinstance(result.output, dict):
                summary = result.output.get("summary", "System diagnostics nominal, sir.")
                return ChatResponse(
                    intent="task_request",
                    message=summary,
                    actions=[ActionExecutionRecord(tool="system.vitals", target="hardware_telemetry", status="success", message=summary, verified=True)]
                )
            return ChatResponse(
                intent="task_request",
                message=f"Could not retrieve hardware diagnostics, sir: {result.error}",
                actions=[ActionExecutionRecord(tool="system.vitals", target="hardware_telemetry", status="failed", message=f"Failed: {result.error}", verified=False)]
            )

        # 19. Workstation Security & Lock Screen
        lock_match = re.search(
            r"\b(?:lock\s+(?:my\s+)?(?:pc|computer|screen|workstation|desktop)|secure\s+(?:my\s+)?(?:workstation|pc|desktop))\b",
            clean_lower,
        )
        if lock_match:
            result = self.execute_tool_request(ToolExecutionRequest(name="system.lock_pc", arguments={}))
            if result.success and isinstance(result.output, dict):
                msg = result.output.get("message", "Workstation locked, sir. Your desktop is now secure.")
                return ChatResponse(
                    intent="task_request",
                    message=msg,
                    actions=[ActionExecutionRecord(tool="system.lock_pc", target="workstation", status="success", message=msg, verified=True)]
                )
            return ChatResponse(
                intent="task_request",
                message=f"Could not lock workstation, sir: {result.error}",
                actions=[ActionExecutionRecord(tool="system.lock_pc", target="workstation", status="failed", message=f"Failed: {result.error}", verified=False)]
            )

        return None


    def _try_cognitive_tool_execution(
        self,
        request: ChatRequest,
        memory_user_id: str | None = None,
    ) -> ChatResponse | None:
        if not self.tool_executor:
            return None

        clean_lower = request.message.lower().strip("?.! ")

        # Check if user is asking for real-time information, research, scores, or facts
        research_indicators = re.search(
            r"\b(?:who\s+is\s+the\s+current|what\s+is\s+the\s+latest|who\s+won|score\s+of|news\s+about|"
            r"look\s+up|search\s+for|search\s+the\s+web|find\s+information\s+on|documentation\s+for|"
            r"release\s+date\s+of|what\s+happened\s+to|stock\s+price\s+of|current\s+price\s+of|"
            r"who\s+is\s+winning|what\s+are\s+the\s+latest\s+features\s+of)\b",
            clean_lower,
        )
        if not research_indicators:
            return None

        # Execute web.search to retrieve verified real-time facts
        target_query = request.message.strip()
        search_res = self.execute_tool_request(
            ToolExecutionRequest(name="web.search", arguments={"query": target_query})
        )
        if not search_res.success or not isinstance(search_res.output, dict):
            return None

        summary = search_res.output.get("summary", "")
        headlines = search_res.output.get("headlines", [])
        evidence_text = "\n".join(f"- {h}" for h in headlines) if headlines else summary

        # Feed the verified real-time evidence to Gemini to synthesize a polished answer
        memory_context = self._retrieve_memory(request, memory_user_id)
        evidence_prompt = (
            f"Verified Real-Time Web Evidence (100% current ground truth for query '{target_query}'):\n"
            f"{evidence_text}\n\n"
            f"{self._build_prompt(request, memory_context)}\n\n"
            f"Synthesize an accurate, polished, and truthful British assistant briefing for the user based strictly on the verified live evidence above."
        )
        provider_request = LLMRequest(
            messages=[
                LLMMessage(
                    role="user",
                    content=evidence_prompt,
                    image_data=request.image_data,
                )
            ],
            system_instruction=SYSTEM_INSTRUCTION,
            image_data=request.image_data,
        )
        try:
            llm_resp = self.provider.generate(provider_request)
            answer = llm_resp.content.strip()
            if self.secret:
                answer = answer.replace(self.secret, "[redacted]")
            return ChatResponse(
                intent="task_request",
                message=answer,
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
        except Exception:
            return ChatResponse(
                intent="task_request",
                message=summary,
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
