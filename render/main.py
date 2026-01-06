import json
import time
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Union

from fastapi import FastAPI, Response
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright


def log_event(event: str, level: str = "info", **fields: Any) -> None:
    payload: Dict[str, Any] = {
        "event": event,
        "level": level,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = value
    print(json.dumps(payload, ensure_ascii=False))


SectionKind = Literal["bullets", "text", "table"]


class SectionBullets(BaseModel):
    title: str
    kind: Literal["bullets"]
    items: List[str] = Field(default_factory=list)


class SectionText(BaseModel):
    title: str
    kind: Literal["text"]
    text: str


class SectionTable(BaseModel):
    title: str
    kind: Literal["table"]
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)


Section = Annotated[
    Union[SectionBullets, SectionText, SectionTable],
    Field(discriminator="kind"),
]


class RenderRequest(BaseModel):
    doc_id: str
    title: str
    sections: List[Section] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="render-service", version="9.4.1")


@app.post("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _build_html(req: RenderRequest) -> str:
    title = _escape_html(req.title)

    parts: List[str] = []
    parts.append("<!doctype html>")
    parts.append("<html><head><meta charset='utf-8' />")
    parts.append(
        """
<style>
  @page { size: A4; margin: 18mm; }
  html, body { padding: 0; margin: 0; }
  body { font-family: Arial, Helvetica, sans-serif; color: #111; font-size: 12.5px; line-height: 1.35; }
  h1 { font-size: 20px; margin: 0 0 10px 0; }
  h2 { font-size: 14.5px; margin: 14px 0 6px 0; }
  .meta { font-size: 10.5px; color: #555; margin-bottom: 10px; }
  .hr { height: 1px; background: #ddd; margin: 10px 0; }
  ul { padding-left: 18px; margin: 6px 0; }
  li { margin: 2px 0; }
  table { width: 100%; border-collapse: collapse; margin: 8px 0 0 0; }
  th, td { border: 1px solid #ddd; padding: 6px 7px; vertical-align: top; }
  th { background: #f4f4f4; text-align: left; }
</style>
"""
    )
    parts.append("</head><body>")

    pack_id = _escape_html(str(req.meta.get("pack_id", "")))
    session_id = _escape_html(str(req.meta.get("session_id", "")))
    doc_id = _escape_html(req.doc_id)

    parts.append(f"<h1>{title}</h1>")
    parts.append(
        "<div class='meta'>"
        f"doc_id: {doc_id}" + (f" · pack_id: {pack_id}" if pack_id else "") + (f" · session_id: {session_id}" if session_id else "") +
        "</div>"
    )
    parts.append("<div class='hr'></div>")

    for section in req.sections:
        section_title = _escape_html(section.title)
        parts.append(f"<h2>{section_title}</h2>")

        if isinstance(section, SectionBullets):
            parts.append("<ul>")
            for item in section.items:
                parts.append(f"<li>{_escape_html(item)}</li>")
            parts.append("</ul>")

        elif isinstance(section, SectionText):
            # Preserve basic line breaks.
            text = _escape_html(section.text).replace("\n", "<br/>")
            parts.append(f"<div>{text}</div>")

        elif isinstance(section, SectionTable):
            parts.append("<table>")
            if section.headers:
                parts.append("<thead><tr>")
                for h in section.headers:
                    parts.append(f"<th>{_escape_html(h)}</th>")
                parts.append("</tr></thead>")
            parts.append("<tbody>")
            for row in section.rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(f"<td>{_escape_html(cell)}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")

    parts.append("</body></html>")
    return "".join(parts)


@app.post("/render")
async def render(req: RenderRequest) -> Response:
    start = time.perf_counter()

    log_event(
        "render_request_start",
        doc_id=req.doc_id,
        sections_count=len(req.sections),
    )

    try:
        html = _build_html(req)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context(offline=True)
            page = await context.new_page()

            await page.set_content(html, wait_until="load")
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
            )

            await context.close()
            await browser.close()

        log_event(
            "render_request_ok",
            doc_id=req.doc_id,
            sections_count=len(req.sections),
            bytes_size=len(pdf_bytes),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
        )
    except Exception as e:
        log_event(
            "render_request_error",
            level="error",
            doc_id=req.doc_id,
            sections_count=len(req.sections),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            error=str(e),
        )
        raise
