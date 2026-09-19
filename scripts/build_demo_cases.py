"""Build saved, real reconstruction cases using the same engine as the API."""
import sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import ALGORITHM_VERSION
from app.analysis import run
from app.domain import AnalysisRequest,SavedAnalysis
from app.storage import store_analysis

if __name__=='__main__':
    for name,start,duration,title in (
        ('sunlight','2024-05-05T01:00:00Z',1,'Осмотр оборудования при солнечном свете'),
        ('tradeoff','2024-05-28T12:00:00Z',2,'Выбор между освещением и погодным прогнозом')):
        request=AnalysisRequest(mode='reconstruction',start=start,duration_hours=duration,
                                search_hours=12,requires_sunlight=True,task_name=title)
        windows,comparison,records=run(request)
        saved=SavedAnalysis(id=uuid4().hex,request=request,windows=windows,comparison=comparison,
                            created_at=datetime.now(timezone.utc),algorithm_version=ALGORITHM_VERSION,source_records=records)
        (ROOT/'research_results'/f'{name}.json').write_text(saved.model_dump_json(indent=2),encoding='utf-8')
        store_analysis(saved)
        print(name,comparison.outcome,[next(f.overlap_minutes for f in w.factors if f.mechanism=='lighting') for w in windows])
