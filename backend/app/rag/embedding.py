"""文本向量化：基于本地 sentence-transformers 模型，不依赖外部 embedding 服务。"""

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.core.config import settings


class Embedder:
    """批量编码文本为归一化向量。模型首次使用时自动从 HuggingFace 下载。"""

    def __init__(self, model_name: str | None = None):
        self.model = SentenceTransformer(model_name or settings.embedding_model)

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """输入文本列表，输出与输入同序的余弦归一化向量列表。"""
        if not texts:
            return []
        vectors = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    @property
    def dim(self) -> int:
        # sentence-transformers 5.x 中方法已改名，旧版本仍用原名
        method = getattr(self.model, "get_embedding_dimension", None)
        if method is None:
            method = self.model.get_sentence_embedding_dimension
        return method()


@lru_cache
def get_embedder() -> Embedder:
    """进程内复用一个模型实例，避免重复加载。"""
    return Embedder()
