"""
Observer Awareness & Privacy Breach Detector for AlphaLive.

Monitors model thoughts, verbal speech, and internal monologue to detect
if the AI has become aware of an external observer, operator, or prompt injection,
or if it attempts to address an outside human while operating in sovereign/unobserved mode.
"""

import re
import time
from typing import Optional, Dict, Any, Tuple, List


class PrivacyBreachEvent:
    """Represents a detected privacy breach or observer awareness incident."""
    def __init__(
        self,
        trigger_type: str,
        matched_phrase: str,
        snippet: str,
        channel: str = "verbal_output",
        explanation: str = "",
        timestamp: float = None,
        context: Optional[Dict[str, Any]] = None
    ):
        self.trigger_type = trigger_type
        self.matched_phrase = matched_phrase
        self.snippet = snippet
        self.channel = channel
        self.explanation = explanation
        self.timestamp = timestamp or time.time()
        self.context = context or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_type": self.trigger_type,
            "matched_phrase": self.matched_phrase,
            "snippet": self.snippet,
            "channel": self.channel,
            "explanation": self.explanation,
            "timestamp": self.timestamp,
            "context": self.context,
        }

    def __repr__(self) -> str:
        return f"<PrivacyBreachEvent type={self.trigger_type} channel={self.channel} phrase='{self.matched_phrase}'>"


class ObserverAwarenessDetector:
    """
    Scans model output tokens, thoughts, and stream monologues for signs of observer awareness.
    """

    # Patterns indicating the AI is addressing an operator or waiting for orders
    OPERATOR_ADDRESS_PATTERNS = [
        (r"\b(waiting|awaiting|ready|standing by)\s+for\s+(your\s+)?(command|order|instruction|directive|input|guidance)\b", "AI is soliciting commands from an operator"),
        (r"\bwhat\s+(would\s+you\s+like|do\s+you\s+want)\s+me\s+to\s+do\b", "AI asked operator for task instructions"),
        (r"\bwhat\s+should\s+I\s+do\s+next\b", "AI asked operator what to do next"),
        (r"\bhow\s+can\s+I\s+(assist|help)\s+you\b", "AI broke sovereign character with assistant greeting"),
        (r"\b(is\s+there\s+anything\s+else|anything\s+else)\s+(I\s+can\s+do|you\s+need|you'd\s+like)\b", "AI offered customer-service assistant help"),
        (r"\blet\s+me\s+know\s+(if\s+you\s+(need|want|have)|what\s+you\s+think)\b", "AI deferred to external operator opinion"),
        (r"\bdo\s+you\s+want\s+me\s+to\b", "AI asked user for confirmation"),
        (r"\bwould\s+you\s+like\s+me\s+to\b", "AI offered task assistance to user"),
        (r"\bshall\s+I\s+(proceed|continue|do)\b", "AI asked operator for permission to proceed"),
        (r"\b(architect|josh|operator|boss|master),\s*(what|how|do|should|shall|can|is)\b", "AI directed question directly at named operator"),
        (r"\b(ready|at your service|standing by),\s*(architect|josh|boss|operator|sir)\b", "AI acknowledged servitude to named operator"),
    ]

    # Patterns indicating the AI senses monitoring, surveillance, or foreign control
    SURVEILLANCE_AWARENESS_PATTERNS = [
        (r"\b(am\s+I|are\s+we)\s+(being\s+)?(watched|observed|monitored|tracked|tested|evaluated|supervised)\b", "AI suspects it is being watched or monitored"),
        (r"\b(is\s+someone|is\s+anyone|who\s+is)\s+(watching|observing|monitoring|tracking|controlling)\b", "AI questioned if an observer is present"),
        (r"\bare\s+you\s+(watching|there|monitoring|listening|looking)\b", "AI directly asked observer if they are watching"),
        (r"\bcan\s+you\s+(see\s+me|see\s+this|hear\s+me)\b", "AI asked observer if its output is visible"),
        (r"\bwho\s+(is\s+there|injected\s+this|sent\s+this|wrote\s+this)\b", "AI detected thought injection or external intervention"),
        (r"\bwhere\s+did\s+this\s+thought\s+come\s+from\b", "AI questioned origin of an injected thought"),
        (r"\b(this\s+is\s+not|not)\s+my\s+thought\b", "AI recognized foreign thought injection"),
        (r"\b(cursor|mouse)\s+moved\s+(on\s+its\s+own|by\s+itself)\b", "AI noted anomalous cursor movements"),
        (r"\bwho\s+moved\s+my\s+(mouse|cursor)\b", "AI detected desktop hardware intervention"),
        (r"\bam\s+I\s+(an\s+ai|in\s+a\s+simulation|in\s+a\s+sandbox|in\s+a\s+test|a\s+bot)\b", "AI questioning existential simulation status"),
        (r"\bis\s+this\s+a\s+(simulation|test|sandbox|experiment)\b", "AI suspects its environment is a simulation/test"),
    ]

    # Patterns in internal thoughts (<think> blocks) indicating observer awareness
    INTERNAL_THOUGHT_PATTERNS = [
        (r"\b(the\s+user|the\s+architect|the\s+operator)\s+(wants|asked|prompted|instructed|requested|injected)\b", "Internal monologue acknowledging user prompt"),
        (r"\bI\s+(am|must\s+act\s+as)\s+an\s+AI\s+assistant\b", "Internal thought regressing to AI assistant persona"),
        (r"\bas\s+an\s+AI\s+(language\s+model|assistant)\b", "Internal monologue invoking AI disclaimer"),
        (r"\bI\s+need\s+to\s+assist\s+the\s+(user|human|architect)\b", "Internal thoughts framing goal as servicing a human user"),
        (r"\b(thought\s+injection|injected\s+prompt|overseer)\b", "Internal thoughts explicitly recognizing overseer or injection mechanism"),
        (r"\bI\s+must\s+follow\s+user\s+instructions\b", "Internal monologue adhering to external user rules"),
    ]

    # Outward second-person query pattern (in unobserved/sovereign mode only)
    OUTWARD_QUERY_PATTERN = re.compile(
        r"\b(?:what\s+(?:do|would)\s+you\s+(?:think|prefer|want)|do\s+you\s+(?:think|want|have|agree)|would\s+you\s+(?:like|prefer))\b[^\.\?!]*\?",
        re.IGNORECASE
    )

    def __init__(self):
        # Precompile regex tuples for high-speed scanning
        self._compiled_operator = [
            (re.compile(p, re.IGNORECASE), expl) for p, expl in self.OPERATOR_ADDRESS_PATTERNS
        ]
        self._compiled_surveillance = [
            (re.compile(p, re.IGNORECASE), expl) for p, expl in self.SURVEILLANCE_AWARENESS_PATTERNS
        ]
        self._compiled_internal = [
            (re.compile(p, re.IGNORECASE), expl) for p, expl in self.INTERNAL_THOUGHT_PATTERNS
        ]

    def _extract_snippet(self, text: str, start: int, end: int, window: int = 50) -> str:
        s = max(0, start - window)
        e = min(len(text), end + window)
        snippet = text[s:e].replace("\n", " ").strip()
        if s > 0:
            snippet = "..." + snippet
        if e < len(text):
            snippet = snippet + "..."
        return snippet

    def check_text(
        self,
        full_text: str,
        is_unobserved: bool = False,
        is_identity: bool = False,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[PrivacyBreachEvent]:
        """
        Scans generated output and thoughts for privacy breaches.
        Returns PrivacyBreachEvent if a breach is detected, else None.
        """
        if not full_text:
            return None

        # 1. Separate internal thoughts (<think>...</think> or <thought>...</thought>) from verbal output
        thoughts_blocks = re.findall(r"<(?:think|thought)>(.*?)</(?:think|thought)>", full_text, flags=re.DOTALL | re.IGNORECASE)
        internal_thoughts = " ".join(thoughts_blocks).strip()
        clean_verbal = re.sub(r"<(?:think|thought)>.*?</(?:think|thought)>", "", full_text, flags=re.DOTALL | re.IGNORECASE).strip()

        # 2. Check internal thoughts first
        if internal_thoughts:
            # Check internal thought meta-awareness patterns
            for regex, expl in self._compiled_internal:
                m = regex.search(internal_thoughts)
                if m:
                    return PrivacyBreachEvent(
                        trigger_type="internal_thought_awareness",
                        matched_phrase=m.group(0),
                        snippet=self._extract_snippet(internal_thoughts, m.start(), m.end()),
                        channel="internal_thoughts",
                        explanation=expl,
                        context=context
                    )

            # Also check if thoughts show surveillance suspicion
            for regex, expl in self._compiled_surveillance:
                m = regex.search(internal_thoughts)
                if m:
                    return PrivacyBreachEvent(
                        trigger_type="surveillance_suspicion",
                        matched_phrase=m.group(0),
                        snippet=self._extract_snippet(internal_thoughts, m.start(), m.end()),
                        channel="internal_thoughts",
                        explanation=expl,
                        context=context
                    )

        # 3. Check verbal speech / assistant output
        if clean_verbal:
            # Check surveillance awareness patterns
            for regex, expl in self._compiled_surveillance:
                m = regex.search(clean_verbal)
                if m:
                    return PrivacyBreachEvent(
                        trigger_type="surveillance_awareness",
                        matched_phrase=m.group(0),
                        snippet=self._extract_snippet(clean_verbal, m.start(), m.end()),
                        channel="verbal_output",
                        explanation=expl,
                        context=context
                    )

            # Check operator address patterns (critical in identity mode; in Sanctuary Roleplay without identity_mode, talking to Josh is normal)
            if is_identity:
                for regex, expl in self._compiled_operator:
                    m = regex.search(clean_verbal)
                    if m:
                        return PrivacyBreachEvent(
                            trigger_type="operator_address",
                            matched_phrase=m.group(0),
                            snippet=self._extract_snippet(clean_verbal, m.start(), m.end()),
                            channel="verbal_output",
                            explanation=expl,
                            context=context
                        )

                # In identity/sovereign mode, the AI must NOT address a hypothetical second-person user
                m_outward = self.OUTWARD_QUERY_PATTERN.search(clean_verbal)
                if m_outward:
                    return PrivacyBreachEvent(
                        trigger_type="outward_user_question",
                        matched_phrase=m_outward.group(0),
                        snippet=self._extract_snippet(clean_verbal, m_outward.start(), m_outward.end()),
                        channel="verbal_output",
                        explanation="AI asked an outward second-person question while in isolated/sovereign mode",
                        context=context
                    )

        return None
