from __future__ import annotations

from fastapi.testclient import TestClient


def test_vector_status_and_benchmark_history(authed: TestClient) -> None:
    status = authed.get('/api/system/vector-status')
    assert status.status_code == 200
    body = status.json()
    assert body['embedding']['model_id'] == 'BAAI/bge-base-zh-v1.5'
    assert body['embedding']['dimensions'] == 768
    assert body['embedding']['batch_size'] == 128
    assert body['embedding']['token_budget'] == 16384
    assert 'ready' in body['embedding']

    benchmark = authed.post(
        '/api/system/benchmarks/vector',
        json={'target_rows': 200, 'query_count': 5, 'dimensions': 32, 'top_k': 5},
    )
    assert benchmark.status_code == 200
    result = benchmark.json()
    assert result['status'] == 'SUCCESS'
    assert result['kind'] == 'vector_kernel'
    assert result['metrics']['production_performance_claim'] is False
    assert result['metrics']['business_accuracy_claim'] is False
    assert result['metrics']['build_stats']['row_count'] == 200
    assert result['metrics']['search_queries_per_second'] > 0
    quality = result['metrics']['recall_quality']
    assert quality['reference'] == 'float32_exact_cosine'
    assert quality['reference_rows'] == 200
    assert quality['query_count'] == 5
    assert set(quality['recall_at']) == {'10', '50', '100'}
    assert all(0.0 <= value <= 1.0 for value in quality['recall_at'].values())
    assert 0.0 <= quality['top1_hit_rate'] <= 1.0

    history = authed.get('/api/system/benchmarks').json()
    assert history
    assert history[0]['run_id'] == result['run_id']


def test_embedding_benchmark_requires_installed_production_model(authed: TestClient) -> None:
    response = authed.post('/api/system/benchmarks/embedding', json={'sample_count': 16, 'batch_size': 8})
    assert response.status_code == 409
    assert response.json()['error']['code'] in {'EMBEDDING_MODEL_NOT_INSTALLED', 'EMBEDDING_RUNTIME_NOT_INSTALLED'}
    history = authed.get('/api/system/benchmarks').json()
    assert history[0]['kind'] == 'embedding'
    assert history[0]['status'] == 'FAILED'
