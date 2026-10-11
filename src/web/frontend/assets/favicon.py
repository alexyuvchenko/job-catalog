"""Tab icon: a green badge with a shield for бронювання."""

from __future__ import annotations

from urllib.parse import quote

FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="8" fill="#0d6b52"/>'
    '<path fill="#fff" d="M16 6.8 23.2 10.2v7.2c0 4.2-3 7.6-7.2 9.6-4.2-2-7.2-5.4-7.2-9.6v-7.2L16 6.8z"/>'
    "</svg>"
)
FAVICON_LINK = '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
FAVICON_DATA_LINK = (
    f'<link rel="icon" href="data:image/svg+xml,{quote(FAVICON_SVG)}" type="image/svg+xml">'
)
