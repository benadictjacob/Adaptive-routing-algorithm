"""
═══════════════════════════════════════════════════════════════════════
  AI DIAGNOSIS ENGINE — Log Analysis, Human Explanation & Fix Suggestions
═══════════════════════════════════════════════════════════════════════

Analyzes container logs using pattern matching and heuristics.
Provides BOTH technical AND human-readable explanations.
Classifies failures into 6 categories.
"""

import re
from typing import Dict, List


# ── Failure Categories ───────────────────────────────────────

FAILURE_CATEGORIES = {
    "startup":    "Startup Failure",
    "crash":      "Application Crash",
    "network":    "Network Error",
    "resource":   "Resource Exhaustion",
    "app_error":  "Application Error",
    "dependency": "Dependency Failure",
}

# ── Error Pattern Database ───────────────────────────────────

ERROR_PATTERNS = [
    {
        "pattern": r"ZeroDivisionError",
        "type": "ZeroDivisionError",
        "category": "app_error",
        "cause": "Code attempted to divide by zero. A denominator variable is 0.",
        "human": "The service crashed because it tried to divide a number by zero — like asking 'what is 10 ÷ 0?'. A calculation in the code received bad input.",
        "fix": "Add a guard: `if denominator != 0:` before division, or use try/except.",
        "severity": "Critical",
    },
    {
        "pattern": r"MemoryError|unable to allocate|OOM|out of memory",
        "type": "MemoryError",
        "category": "resource",
        "cause": "Process exhausted available memory. Large data structures or infinite loops creating objects.",
        "human": "The service stopped because it ran out of memory — it tried to use more RAM than the system has available. Think of it like trying to pour 2 gallons into a 1-gallon container.",
        "fix": "Use streaming/chunked processing. Add memory limits: `mem_limit: 512m`. Consider pagination.",
        "severity": "Critical",
    },
    {
        "pattern": r"ImportError|ModuleNotFoundError|No module named",
        "type": "ImportError",
        "category": "startup",
        "cause": "A required Python module is not installed in the container image.",
        "human": "The service couldn't start because it needs a software library that isn't installed — like trying to open a Word document without Microsoft Word installed.",
        "fix": "Add the missing package to requirements.txt and rebuild: `docker build -t <image> .`",
        "severity": "Critical",
    },
    {
        "pattern": r"ConnectionRefusedError|Connection refused|ECONNREFUSED",
        "type": "ConnectionRefused",
        "category": "dependency",
        "cause": "Service tried to connect to another service/database that is not running.",
        "human": "The service tried to talk to another service (like a database) but nobody answered — the other service is either down or hasn't started yet.",
        "fix": "Ensure dependency services are running. Add retry logic with exponential backoff.",
        "severity": "Critical",
    },
    {
        "pattern": r"TimeoutError|timed out|deadline exceeded|timeout",
        "type": "Timeout",
        "category": "network",
        "cause": "An operation took too long, exceeding the configured timeout.",
        "human": "The service was waiting too long for a response and gave up — like calling someone who never picks up the phone.",
        "fix": "Increase timeout values. Optimize slow queries. Add circuit breaker pattern.",
        "severity": "Warning",
    },
    {
        "pattern": r"KeyError",
        "type": "KeyError",
        "category": "app_error",
        "cause": "Code tried to access a dictionary key that doesn't exist.",
        "human": "The service looked for a piece of data that doesn't exist — like looking up a word in a dictionary that isn't there.",
        "fix": "Use `dict.get('key', default)` instead of `dict['key']`. Validate input data.",
        "severity": "Warning",
    },
    {
        "pattern": r"TypeError.*NoneType|AttributeError.*NoneType",
        "type": "NoneTypeError",
        "category": "app_error",
        "cause": "A function returned None when a value was expected.",
        "human": "The service expected to receive data but got nothing back — like ordering food and receiving an empty plate.",
        "fix": "Add null checks: `if result is not None:`. Ensure functions always return a value.",
        "severity": "Warning",
    },
    {
        "pattern": r"TypeError",
        "type": "TypeError",
        "category": "app_error",
        "cause": "An operation was applied to an object of the wrong type.",
        "human": "The service tried to do something with the wrong type of data — like trying to multiply a word by a number.",
        "fix": "Check variable types before operations. Use isinstance() to debug.",
        "severity": "Warning",
    },
    {
        "pattern": r"FileNotFoundError|No such file|ENOENT",
        "type": "FileNotFoundError",
        "category": "startup",
        "cause": "The container tried to access a file that doesn't exist.",
        "human": "The service tried to open a file that doesn't exist — the expected file may not have been included in the container image.",
        "fix": "Ensure files are COPYed in the Dockerfile. Use absolute paths inside the container.",
        "severity": "Warning",
    },
    {
        "pattern": r"PermissionError|Permission denied|EACCES",
        "type": "PermissionError",
        "category": "startup",
        "cause": "The process doesn't have permission to access a file or port.",
        "human": "The service doesn't have permission to access something it needs — like trying to open a locked door without the key.",
        "fix": "Use `chmod` in Dockerfile. Ensure mounted volumes have correct permissions.",
        "severity": "Warning",
    },
    {
        "pattern": r"signal:? ?killed|exit code:? ?137|SIGKILL",
        "type": "OOMKilled",
        "category": "resource",
        "cause": "Container was killed by the kernel OOM killer. Exit code 137 = SIGKILL.",
        "human": "The system forcefully stopped this service because it was using too much memory. The operating system killed it to protect other services.",
        "fix": "Increase the container memory limit in docker-compose.yml. Check for memory leaks.",
        "severity": "Critical",
    },
    {
        "pattern": r"RuntimeError.*connections? exhausted|pool.*exhausted",
        "type": "ConnectionPoolExhausted",
        "category": "resource",
        "cause": "All database/network connections are in use and no new ones can be created.",
        "human": "The service has used up all its available connections to the database — like a phone switchboard where all lines are busy.",
        "fix": "Increase connection pool size. Add connection timeouts. Close connections properly.",
        "severity": "Critical",
    },
    {
        "pattern": r"RuntimeError",
        "type": "RuntimeError",
        "category": "crash",
        "cause": "A general runtime error — catch-all for unexpected conditions.",
        "human": "The service encountered an unexpected problem while running. Something went wrong that the developers didn't anticipate.",
        "fix": "Check the full error message. Add defensive programming with try/except.",
        "severity": "Critical",
    },
    {
        "pattern": r"ECONNRESET|connection reset|broken pipe",
        "type": "ConnectionReset",
        "category": "network",
        "cause": "A network connection was unexpectedly closed by the remote end.",
        "human": "The network connection was suddenly dropped — like a phone call that gets cut off mid-conversation.",
        "fix": "Add retry logic. Check network stability between containers. Verify the remote service is stable.",
        "severity": "Warning",
    },
    {
        "pattern": r"DNS.*failed|name.*resolution|ENOTFOUND|getaddrinfo",
        "type": "DNSResolutionFailure",
        "category": "network",
        "cause": "Could not resolve the hostname of a service. DNS lookup failed.",
        "human": "The service couldn't find the address of another service — like looking up a phone number but the directory doesn't have it listed.",
        "fix": "Check service names in Docker compose. Ensure both services are on the same network.",
        "severity": "Critical",
    },
]

# ── Exit Code Explanations ───────────────────────────────────

EXIT_CODE_EXPLANATIONS = {
    0: ("Clean exit", "The service stopped normally — no errors."),
    1: ("General error", "The service crashed due to an unhandled error in the code."),
    2: ("Misuse of command", "The service was started with incorrect command-line arguments."),
    126: ("Command not executable", "The startup command exists but cannot be executed — check file permissions."),
    127: ("Command not found", "The startup command doesn't exist in the container — check your Dockerfile CMD."),
    137: ("Killed (SIGKILL)", "The service was forcefully stopped because it used too much memory."),
    139: ("Segfault (SIGSEGV)", "The service crashed due to a memory access violation — a bug in native code."),
    143: ("Terminated (SIGTERM)", "The service was asked to stop gracefully and did so."),
}


class AIAnalyzer:
    """
    Analyzes error logs and provides BOTH technical and human-readable diagnosis.
    Classifies failures into 6 categories.
    """

    def __init__(self):
        self.analysis_history: List[Dict] = []

    def analyze(self, logs: str, context: Dict = None) -> Dict:
        """
        Analyze error logs and return structured diagnosis with human explanation.
        """
        context = context or {}
        error_line = self._extract_error_line(logs)
        exit_code = context.get("exit_code") or self._extract_exit_code(logs)

        # Match against patterns
        for pattern_info in ERROR_PATTERNS:
            if re.search(pattern_info["pattern"], logs, re.IGNORECASE):
                result = {
                    "error_type": pattern_info["type"],
                    "category": FAILURE_CATEGORIES.get(pattern_info["category"], "Unknown"),
                    "error_summary": f"{pattern_info['type']} detected in container logs",
                    "root_cause": pattern_info["cause"],
                    "human_explanation": pattern_info["human"],
                    "fix_instructions": pattern_info["fix"],
                    "fix_steps": self._generate_fix_steps(pattern_info),
                    "code_snippet": self._extract_code_context(logs),
                    "severity": pattern_info["severity"],
                    "confidence": 0.85,
                    "raw_error_line": error_line,
                }
                self.analysis_history.append(result)
                return result

        # Exit code based analysis
        if exit_code and exit_code in EXIT_CODE_EXPLANATIONS:
            tech, human = EXIT_CODE_EXPLANATIONS[exit_code]
            result = {
                "error_type": f"ExitCode_{exit_code}",
                "category": "Application Crash" if exit_code != 0 else "Clean Exit",
                "error_summary": tech,
                "root_cause": f"Container exited with code {exit_code}: {tech}",
                "human_explanation": human,
                "fix_instructions": "Check the application logs for detailed error information.",
                "fix_steps": ["1. Check container logs", "2. Review application code", "3. Rebuild and redeploy"],
                "code_snippet": "",
                "severity": "Critical" if exit_code not in (0, 143) else "Info",
                "confidence": 0.6,
                "raw_error_line": error_line,
            }
            self.analysis_history.append(result)
            return result

        # Fallback
        result = {
            "error_type": "Unknown",
            "category": "Application Crash",
            "error_summary": "Unrecognized error pattern in logs",
            "root_cause": f"Container reported an error. Error: {error_line[:200]}",
            "human_explanation": "Something went wrong with this service, but the exact cause isn't clear from the logs. Manual investigation may be needed.",
            "fix_instructions": "Review the full container logs for details.",
            "fix_steps": ["1. Check docker service logs", "2. Review recent code changes", "3. Restart the service"],
            "code_snippet": "",
            "severity": "Warning",
            "confidence": 0.3,
            "raw_error_line": error_line,
        }
        self.analysis_history.append(result)
        return result

    def _generate_fix_steps(self, pattern: Dict) -> List[str]:
        """Generate numbered fix steps from the fix instructions."""
        fix = pattern["fix"]
        parts = [p.strip() for p in fix.split(".") if p.strip()]
        return [f"{i+1}. {p}" for i, p in enumerate(parts[:5])]

    def _extract_error_line(self, logs: str) -> str:
        lines = logs.strip().split("\n")
        for line in reversed(lines):
            if re.search(r"Error:|Exception:|Traceback|FATAL|CRITICAL", line, re.IGNORECASE):
                cleaned = re.sub(r"^\d{4}-\d{2}-\d{2}T\S+\s*", "", line).strip()
                if cleaned:
                    return cleaned
        return lines[-1] if lines else ""

    def _extract_exit_code(self, logs: str) -> int:
        m = re.search(r"exit code:?\s*(\d+)", logs, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _extract_code_context(self, logs: str) -> str:
        lines = logs.strip().split("\n")
        code_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("File ") or stripped.startswith('File "'):
                code_lines.append(stripped)
            elif code_lines and not stripped.startswith("Traceback"):
                code_lines.append(stripped)
                if len(code_lines) >= 6:
                    break
        return "\n".join(code_lines) if code_lines else ""

    def get_history(self) -> List[Dict]:
        return self.analysis_history[-50:]
