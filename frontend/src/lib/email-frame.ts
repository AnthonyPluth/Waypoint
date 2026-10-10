export type Picture = { type: string; data: string };

export const PICTURE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
export const FRAME_SANDBOX = "allow-popups allow-popups-to-escape-sandbox";
export const FRAME_POLICY = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'";

const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

const SHEET = `
  :root { color-scheme: light; }
  html, body { margin: 0; }
  body { padding: 12px; background: #ffffff; color: #1a1a1a; font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; overflow-wrap: anywhere; }
  img { max-width: 100%; height: auto; }
  table { max-width: 100%; }
  a { color: #0b57d0; }
  a[title]:hover::after, a[title]:focus::after { content: attr(title); position: fixed; left: 0; right: 0; bottom: 0; z-index: 2; padding: 4px 8px; background: #1a1a1a; color: #ffffff; font: 12px/1.4 system-ui, sans-serif; word-break: break-all; }
`;

const pictureAddress = (p: Picture | undefined) => (p && PICTURE_TYPES.includes(p.type) && BASE64.test(p.data) ? `data:${p.type};base64,${p.data}` : null);

export function emailDocument(layout: string, pictures: Picture[]): string {
  const page = new DOMParser().parseFromString(`<!doctype html><body>${layout}`, "text/html");
  for (const img of Array.from(page.body.querySelectorAll("img"))) {
    const address = pictureAddress(pictures[Number(img.getAttribute("data-image"))]);
    img.removeAttribute("data-image");
    if (address) img.setAttribute("src", address);
    else img.replaceWith(page.createTextNode(img.getAttribute("alt") ?? ""));
  }
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${FRAME_POLICY}"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${SHEET}</style></head><body>${page.body.innerHTML}</body></html>`;
}
