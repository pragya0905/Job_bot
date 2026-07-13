from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


class SourceToggle(BaseModel):
    enabled: bool = False


class SourcesConfig(BaseModel):
    remoteok: SourceToggle = SourceToggle(enabled=True)
    weworkremotely: SourceToggle = SourceToggle(enabled=True)
    linkedin: SourceToggle = SourceToggle(enabled=False)
    indeed: SourceToggle = SourceToggle(enabled=False)


class FiltersConfig(BaseModel):
    title_keywords: list[str] = []
    locations: list[str] = []


class ScoringConfig(BaseModel):
    model: str = "gemma3:4b"
    temperature: float = 0.0


class TailoringConfig(BaseModel):
    score_threshold: int = 75
    model: str = "gemma4:26b"
    temperature: float = 0.2


class OllamaConfig(BaseModel):
    host: str = "http://localhost:11434"


class AppConfig(BaseModel):
    database_path: str = "data/jobpilot.db"
    resume_dir: str = "data/resumes"
    sources: SourcesConfig = SourcesConfig()
    filters: FiltersConfig = FiltersConfig()
    scoring: ScoringConfig = ScoringConfig()
    tailoring: TailoringConfig = TailoringConfig()
    ollama: OllamaConfig = OllamaConfig()

    @property
    def database_abs_path(self) -> Path:
        return PROJECT_ROOT / self.database_path

    @property
    def resume_dir_abs_path(self) -> Path:
        return PROJECT_ROOT / self.resume_dir


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found at {path}. Copy config.example.yaml to config.yaml first."
        )
    raw = yaml.safe_load(path.read_text()) or {}
    return AppConfig.model_validate(raw)


@lru_cache
def get_config() -> AppConfig:
    return load_config()
