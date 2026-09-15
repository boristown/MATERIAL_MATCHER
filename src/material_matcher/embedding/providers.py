from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from typing import Sequence

import numpy as np

from material_matcher.domain.errors import DomainError
from material_matcher.embedding.base import EmbeddingSpec, normalize_embeddings
from material_matcher.embedding.batching import token_budget_batches


def _sha256_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8")); digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


class DeterministicEmbeddingProvider:
    """Small deterministic provider used only by tests/benchmark plumbing."""

    def __init__(self, dimensions: int = 32) -> None:
        self._spec = EmbeddingSpec("deterministic_test", "deterministic-test-v1", dimensions, "test-only", 256, True, "float32")

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    def token_lengths(self, texts: Sequence[str]) -> list[int]:
        return [max(1, len(text)) for text in texts]

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        result = np.empty((len(texts), self.spec.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            material = b""; counter = 0
            while len(material) < self.spec.dimensions:
                material += hashlib.sha256(text.encode("utf-8") + counter.to_bytes(4, "little")).digest(); counter += 1
            values = np.frombuffer(material[: self.spec.dimensions], dtype=np.uint8).astype(np.float32)
            result[row] = values / 127.5 - 1.0
        return normalize_embeddings(result)

    def embed_batched(self, texts: Sequence[str], *, max_batch_size: int, token_budget: int) -> np.ndarray:
        if not texts:
            return np.empty((0, self.spec.dimensions), dtype=np.float32)
        lengths = [min(item, self.spec.max_length) for item in self.token_lengths(texts)]
        output = np.empty((len(texts), self.spec.dimensions), dtype=np.float32)
        for indexes in token_budget_batches(lengths, max_batch_size=max_batch_size, token_budget=token_budget):
            vectors = self.embed([texts[index] for index in indexes])
            output[np.asarray(indexes, dtype=np.int64)] = vectors
        return normalize_embeddings(output)


class OnnxLocalEmbeddingProvider:
    def __init__(self, *, model_dir: Path, model_id: str, dimensions: int, max_length: int, precision: str = "int8", intra_threads: int = 0) -> None:
        tokenizer_path = model_dir / "tokenizer.json"
        candidates = [model_dir / "model_int8.onnx", model_dir / "model.onnx"] if precision == "int8" else [model_dir / "model.onnx", model_dir / "model_int8.onnx"]
        model_path = next((path for path in candidates if path.exists()), None)
        if model_path is None or not tokenizer_path.exists():
            raise DomainError(
                "EMBEDDING_MODEL_NOT_INSTALLED",
                f"未找到本地 Embedding 模型文件，请将 {model_id} 的 tokenizer.json 和 ONNX 模型安装到 {model_dir}",
                status_code=409,
                details={"model_dir": str(model_dir), "model_id": model_id},
            )
        try:
            import onnxruntime as ort  # type: ignore
            from tokenizers import Tokenizer  # type: ignore
        except ImportError as exc:
            raise DomainError(
                "EMBEDDING_RUNTIME_NOT_INSTALLED",
                "当前运行环境未安装 onnxruntime/tokenizers，请安装 material-matcher[embedding] 离线依赖包",
                status_code=409,
            ) from exc
        options = ort.SessionOptions()
        if intra_threads > 0:
            options.intra_op_num_threads = intra_threads
        self._session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._input_names = {item.name for item in self._session.get_inputs()}
        self._spec = EmbeddingSpec(
            provider="onnx_local",
            model_id=model_id,
            dimensions=dimensions,
            model_sha256=_sha256_files([model_path, tokenizer_path]),
            max_length=max_length,
            normalize=True,
            precision=precision,
        )

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    def token_lengths(self, texts: Sequence[str]) -> list[int]:
        if not texts:
            return []
        return [len(item.ids) for item in self._tokenizer.encode_batch(list(texts))]

    def _run_ids(self, sequences: list[list[int]]) -> np.ndarray:
        if not sequences:
            return np.empty((0, self.spec.dimensions), dtype=np.float32)
        max_len = max(1, max(len(item) for item in sequences))
        input_ids = np.zeros((len(sequences), max_len), dtype=np.int64)
        attention_mask = np.zeros((len(sequences), max_len), dtype=np.int64)
        for row, ids in enumerate(sequences):
            if ids:
                input_ids[row, : len(ids)] = ids
                attention_mask[row, : len(ids)] = 1
        feeds: dict[str, np.ndarray] = {}
        if "input_ids" in self._input_names: feeds["input_ids"] = input_ids
        if "attention_mask" in self._input_names: feeds["attention_mask"] = attention_mask
        if "token_type_ids" in self._input_names: feeds["token_type_ids"] = np.zeros_like(input_ids)
        outputs = self._session.run(None, feeds)
        if not outputs:
            raise DomainError("EMBEDDING_OUTPUT_INVALID", "Embedding 模型未返回向量结果", status_code=500)
        tensor = np.asarray(outputs[0], dtype=np.float32)
        vectors = tensor[:, 0, :] if tensor.ndim == 3 else tensor
        if vectors.ndim != 2 or vectors.shape[1] != self.spec.dimensions:
            raise DomainError(
                "EMBEDDING_DIMENSION_MISMATCH",
                f"Embedding 输出维度 {vectors.shape if hasattr(vectors, 'shape') else 'unknown'} 与配置 {self.spec.dimensions} 不一致",
                status_code=500,
            )
        return normalize_embeddings(vectors)

    def embed_batched(self, texts: Sequence[str], *, max_batch_size: int, token_budget: int) -> np.ndarray:
        if not texts:
            return np.empty((0, self.spec.dimensions), dtype=np.float32)
        encoded = self._tokenizer.encode_batch(list(texts))
        clipped = [item.ids[: self.spec.max_length] for item in encoded]
        lengths = [max(1, len(item)) for item in clipped]
        output = np.empty((len(texts), self.spec.dimensions), dtype=np.float32)
        for indexes in token_budget_batches(lengths, max_batch_size=max_batch_size, token_budget=token_budget):
            vectors = self._run_ids([clipped[index] for index in indexes])
            output[np.asarray(indexes, dtype=np.int64)] = vectors
        return normalize_embeddings(output)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        count = max(1, len(texts))
        return self.embed_batched(texts, max_batch_size=count, token_budget=count * self.spec.max_length)


def create_embedding_provider(settings: object, provider_name: str | None = None, model_id: str | None = None, dimensions: int | None = None, max_length: int | None = None, precision: str | None = None):
    provider = provider_name or str(getattr(settings, "embedding_provider"))
    if provider == "onnx_local":
        return OnnxLocalEmbeddingProvider(
            model_dir=Path(getattr(settings, "embedding_model_root")) / (model_id or str(getattr(settings, "embedding_model_id"))),
            model_id=model_id or str(getattr(settings, "embedding_model_id")),
            dimensions=dimensions or int(getattr(settings, "embedding_dimensions")),
            max_length=max_length or int(getattr(settings, "embedding_max_length")),
            precision=precision or str(getattr(settings, "embedding_precision")),
            intra_threads=int(getattr(settings, "embedding_intra_threads", 0)),
        )
    raise DomainError("EMBEDDING_PROVIDER_NOT_FOUND", f"不支持的 Embedding Provider：{provider}", status_code=422)


def embedding_runtime_status(settings: object, model_id: str | None = None) -> dict[str, object]:
    selected_model = model_id or str(getattr(settings, "embedding_model_id"))
    model_dir = Path(getattr(settings, "embedding_model_root")) / selected_model
    tokenizer = model_dir / "tokenizer.json"
    model = next((path for path in (model_dir / "model_int8.onnx", model_dir / "model.onnx") if path.exists()), None)
    runtime_installed = importlib.util.find_spec("onnxruntime") is not None and importlib.util.find_spec("tokenizers") is not None
    model_installed = tokenizer.exists() and model is not None
    return {
        "provider": str(getattr(settings, "embedding_provider")),
        "model_id": selected_model,
        "dimensions": int(getattr(settings, "embedding_dimensions")),
        "max_length": int(getattr(settings, "embedding_max_length")),
        "precision": str(getattr(settings, "embedding_precision")),
        "model_dir": str(model_dir),
        "runtime_installed": runtime_installed,
        "model_installed": model_installed,
        "ready": runtime_installed and model_installed,
    }
