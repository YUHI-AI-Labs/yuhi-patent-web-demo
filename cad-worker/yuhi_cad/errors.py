"""Structured errors. Every error carries an actionable Japanese message."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CadWorkerError(Exception):
    code: str
    message_ja: str
    detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message_ja": self.message_ja,
                "detail": self.detail,
            }
        }


UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
CAD_PARSE_FAILED = "CAD_PARSE_FAILED"
STEP_BACKEND_MISSING = "STEP_BACKEND_MISSING"
EMPTY_GEOMETRY = "EMPTY_GEOMETRY"


def unsupported(ext: str) -> CadWorkerError:
    return CadWorkerError(
        UNSUPPORTED_FORMAT,
        "この形式のファイルはまだ扱えません。STEP / STP / DXF / STL / PDF / PNG / JPG のいずれかをお試しください。",
        f"extension={ext}",
    )


def parse_failed(detail: str) -> CadWorkerError:
    return CadWorkerError(
        CAD_PARSE_FAILED,
        "ファイルの形状を読み取れませんでした。ファイルが破損しているか、対応していない表現が含まれている可能性があります。",
        detail,
    )


def step_backend_missing(detail: str) -> CadWorkerError:
    return CadWorkerError(
        STEP_BACKEND_MISSING,
        "STEP解析エンジンを読み込めませんでした。アプリを再インストールすると復旧する場合があります。",
        detail,
    )
