import json
import re
from pathlib import Path

from app.report import build_report


def test_offline_report_cannot_escape_script_and_retains_snapshot():
    analysis = json.loads((Path(__file__).parents[1]/'research_results/sunlight.json').read_text())
    attack = '</script><script>alert(1)</script><img src=x onerror=alert(2)>'
    analysis['request']['task_name'] = attack
    result = build_report(analysis)
    assert result.count('<script>') == 1
    assert result.count('</script>') == 1
    script = result.split('<script>', 1)[1].split('</script>')[0]
    assert attack not in script
    assert not re.search(r'^import |^export ', script, re.M)
    snapshot = script.split('\nconst snapshot = ', 1)[1].split(';document.open()', 1)[0]
    assert json.loads(snapshot) == analysis
