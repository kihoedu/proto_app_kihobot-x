import os
import chromadb
from chromadb.utils import embedding_functions

_client = None
_collection = None

CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma_db")


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection

    _client = chromadb.PersistentClient(path=CHROMA_PATH)
    ef = embedding_functions.DefaultEmbeddingFunction()
    _collection = _client.get_or_create_collection(
        name="essay_references",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    # 샘플 데이터가 없으면 시드 데이터 삽입
    if _collection.count() == 0:
        _seed_sample_data(_collection)
    return _collection


def _seed_sample_data(col):
    """개발용 샘플 채점 사례 삽입"""
    samples = [
        {
            "id": "ref_001",
            "text": "환경 문제는 개인의 노력만으로는 해결할 수 없다. 구조적 변화가 필요하다.",
            "dimension": "logic",
            "score": "85",
            "feedback": "주장은 명확하나 반론 고려가 부족함"
        },
        {
            "id": "ref_002",
            "text": "디지털 전환 시대에 교육의 역할은 비판적 사고력 함양에 있다.",
            "dimension": "content",
            "score": "90",
            "feedback": "주제 이해도 높고 다각도 분석 우수"
        },
        {
            "id": "ref_003",
            "text": "인공지능이 인간의 일자리를 대체하는 것은 불가피하지만, 새로운 직업군을 창출한다.",
            "dimension": "logic",
            "score": "78",
            "feedback": "논리 흐름 양호하나 근거 보강 필요"
        },
        {
            "id": "ref_004",
            "text": "청소년의 스마트폰 과의존 문제는 가정과 학교, 사회가 함께 해결해야 한다.",
            "dimension": "content",
            "score": "82",
            "feedback": "핵심 내용 포함, 구체적 방안 제시 필요"
        },
        {
            "id": "ref_005",
            "text": "기후변화 대응을 위한 탄소세 도입은 경제적 효율성과 환경 보호를 동시에 달성할 수 있다.",
            "dimension": "fact_check",
            "score": "88",
            "feedback": "사실 근거 탄탄, 경제 지표 인용 적절"
        },
    ]
    col.add(
        ids=[s["id"] for s in samples],
        documents=[s["text"] for s in samples],
        metadatas=[{k: v for k, v in s.items() if k != "id" and k != "text"}
                   for s in samples],
    )


def get_similar_essays(essay_text: str, dimension: str, k: int = 2) -> list[dict]:
    """유사 채점 사례 검색"""
    col = _get_collection()
    results = col.query(
        query_texts=[essay_text[:500]],
        n_results=min(k, col.count()),
        where={"dimension": dimension} if col.count() >= 10 else None,
    )
    output = []
    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i]
        output.append({
            "text": doc,
            "score": meta.get("score", "N/A"),
            "feedback": meta.get("feedback", ""),
        })
    return output


def add_essay_reference(
    essay_id: str,
    essay_text: str,
    dimension: str,
    score: float,
    feedback: str,
):
    """교사가 검토한 채점 결과를 RAG DB에 추가"""
    col = _get_collection()
    col.add(
        ids=[essay_id],
        documents=[essay_text[:500]],
        metadatas=[{
            "dimension": dimension,
            "score": str(score),
            "feedback": feedback,
        }],
    )
