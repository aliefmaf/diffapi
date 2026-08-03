
import re

# HELPER

def parse_added_lines(diff_text):
    """Yields (file_path, line_number, line_content) for each added line."""

    current_file = None
    new_line_num = None

    for raw_line in diff_text.split("\n"):
        if raw_line.startswith("+++ "):
            # e.g. "+++ b/src/db.ts" -> "src/db.ts"
            current_file = raw_line[4:].strip()
            if current_file.startswith("b/"):
                current_file = current_file[2:]

        elif raw_line.startswith("@@"):
            # e.g. "@@ -38,6 +39,7 @@" -> new file starts at line 39
            match = re.search(r"\+(\d+)", raw_line)
            if match:
                new_line_num = int(match.group(1))

        elif raw_line.startswith("+++"):
            continue  # already handled above, skip

        elif raw_line.startswith("+"):
            content = raw_line[1:]  # strip the leading '+'
            yield (current_file, new_line_num, content)
            new_line_num += 1

        elif not raw_line.startswith("-"):
            # context line (unchanged) — still advances new-file line count
            if new_line_num is not None:
                new_line_num += 1



# MOCK PROVIDER RULES

SQL_KEYWORDS = r"(SELECT|INSERT|UPDATE|DELETE)"
API_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
    re.IGNORECASE
)
SQL_CONCAT_PATTERN = re.compile(
    rf"['\"][^'\"]*{SQL_KEYWORDS}[^'\"]*['\"]\s*\+", re.IGNORECASE
)



def check_mock_001(line):
    return "eval(" in line

def check_mock_002(line):
    return bool(API_KEY_PATTERN.search(line))

def check_mock_003(line):
    return bool(SQL_CONCAT_PATTERN.search(line))



def run_mock_provider(diff_text):
    findings = []
    for file_path, line_num, content in parse_added_lines(diff_text):
        if check_mock_001(content):
            findings.append(make_finding("MOCK-001", "critical", "security",
                                          file_path, line_num, "eval usage", content))
        if check_mock_002(content):
            findings.append(make_finding("MOCK-002", "critical", "security",
                                          file_path, line_num, "hardcoded credential", content))
        if check_mock_003(content):
            findings.append(make_finding("MOCK-003", "high", "security",
                                          file_path, line_num, "SQL string concatenation", content))
    return findings



def make_finding(rule_id, severity, category, path, line, title, evidence):
    return {
        "id": f"{rule_id}:{path}:{line}",
        "ruleId": rule_id,
        "path": path,
        "line": line,
        "severity": severity,
        "category": category,
        "title": title,
        "evidence": evidence.strip()
    }



