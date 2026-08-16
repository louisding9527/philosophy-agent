"""文本向量化：基于本地 sentence-transformers 模型，优先用 GPU（DirectML）加速。

DirectML（AMD/部分 NVIDIA）通过 torch-directml 启用；torch-directml 不支持
inference 模式下的张量切片（version_counter 报错），因此用 no_grad 替代
inference_mode。ST 的 @torch.inference_mode() 装饰器在导入时捕获函数对象，
所以注册必须在导入 sentence_transformers 之前完成。
"""

import logging
from functools import lru_cache
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_DML_REGISTERED = False


def _register_dml() -> bool:
    """注册 DirectML 后端并替换 inference_mode，进程内只需一次。"""
    global _DML_REGISTERED
    if _DML_REGISTERED:
        return True
    try:
        import torch
        import torch_directml

        torch.utils.rename_privateuse1_backend("dml")
        torch._register_device_module("dml", torch_directml.PrivateUse1Module)
        torch.inference_mode = lambda *args, **kwargs: torch.no_grad()
        _DML_REGISTERED = True
        return True
    except Exception:
        return False


_DEVICE = settings.embedding_device
if _DEVICE != "cpu" and _register_dml():
    _DEVICE = "dml"

from sentence_transformers import SentenceTransformer  # noqa: E402


def _resolve_device() -> str:
    """设备选择：settings 显式指定优先；否则有 DirectML 用 GPU，退回 CPU。"""
    device = settings.embedding_device
    if device and device != "auto":
        return device
    return "dml" if _DML_REGISTERED else "cpu"


def _resolve_model_path(model_name: str) -> str:
    """把模型名解析成本地缓存目录；走 transformers 的本地目录加载逻辑，
    避免联网解析 revision 和意外触发下载。"""
    try:
        from huggingface_hub import try_to_load_from_cache

        config_path = try_to_load_from_cache(model_name, "config.json")
    except Exception:
        config_path = None
    if config_path and Path(config_path).parent.is_dir():
        return str(Path(config_path).parent)
    return model_name


class Embedder:
    """批量编码文本为归一化向量。模型首次使用时自动从 HuggingFace 下载（已缓存则离线加载）。"""

    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.device = device or _resolve_device()
        self.model = SentenceTransformer(
            _resolve_model_path(model_name or settings.embedding_model),
            device=self.device,
            # torch-directml 的 fp16 SDPA 路径会触发 dml_util.h DML_CHECK 崩溃，
            # 用 eager 注意力绕开（fp32 不受影响）
            model_kwargs={"attn_implementation": "eager"},
        )
        # DirectML 下用 fp16：显存与计算量减半，长片段（800 字左右）不容易撑爆显存
        if self.device == "dml":
            try:
                self.model[0].model.half()
            except Exception:
                pass
        # DML 长片段 attention 显存按 batch 线性增长，16 为稳定值
        self.batch_size = 16 if self.device == "dml" else 32

    def embed(self, texts: list[str], batch_size: int | None = None) -> list[list[float]]:
        """输入文本列表，输出与输入同序的余弦归一化向量列表。

        显存不足（其他程序占用 GPU 时常见）自动降半 batch 重试，
        避免整批向量化失败；batch 降到 1 仍失败则原样抛出。
        """
        if not texts:
            return []
        batch = batch_size or self.batch_size
        try:
            vectors = self.model.encode(
                texts,
                batch_size=batch,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except RuntimeError as exc:
            if "video memory" not in str(exc) or batch <= 1:
                raise
            logger.warning("向量化 batch %s 显存不足，降为 %s 重试：%s", batch, batch // 2, exc)
            return self.embed(texts, batch_size=batch // 2)
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
