"""Write a static dist/index.html image browser for the generated screenshots.

Self-contained: the image manifest is embedded as JSON so the page works when
opened directly via file:// (no fetch / web server needed).
"""
import json
from pathlib import Path
from typing import Any, Dict, List

# Imported lazily-friendly: builder passes a BuildReport, but we only touch
# `.succeeded`, so we keep the type loose to avoid a circular import.


def _manifest(dist_dir: Path, report: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for shot in report.succeeded:
        # `shot.name` is relative to the brand folder, e.g.
        #   "ios/phone/en/03_x.png" or "Clean/ios/phone/en/03_x_Clean.png".
        parts = Path(shot.name).parts
        if parts and parts[0] == "Clean":
            variant, parts = "Clean", parts[1:]
        else:
            variant = "Decorated"
        os_ = parts[0] if len(parts) > 0 else "other"
        form = parts[1] if len(parts) > 1 else "phone"
        lang = parts[2] if len(parts) > 2 else "en"
        file = parts[-1] if parts else shot.name
        try:
            src = str(shot.path.relative_to(dist_dir).as_posix())
        except ValueError:
            src = f"{shot.brand}/{shot.name}"
        items.append({
            "src": src,
            "brand": shot.brand,
            "os": os_,
            "form": form,
            "lang": lang,
            "variant": variant,
            "file": file,
            "w": shot.width,
            "h": shot.height,
        })
    items.sort(key=lambda i: (i["brand"], i["variant"], i["os"], i["form"], i["lang"], i["file"]))
    return items


def write_gallery(dist_dir: Path, report: Any) -> Path:
    """Write dist/index.html. Returns the path."""
    data = _manifest(dist_dir, report)
    html = _TEMPLATE.replace("/*__DATA__*/", json.dumps(data))
    out = dist_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Screenshot Builder — gallery</title>
<style>
  :root { --bg:#0e1116; --panel:#171b22; --line:#272d38; --fg:#e6e9ef; --muted:#8b94a3; --accent:#4f9dff; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         background:var(--bg); color:var(--fg); }
  header { position:sticky; top:0; z-index:5; background:var(--panel); border-bottom:1px solid var(--line);
           padding:12px 16px; display:flex; flex-wrap:wrap; gap:10px 16px; align-items:center; }
  header h1 { font-size:15px; margin:0 12px 0 0; font-weight:600; }
  header .count { color:var(--muted); margin-left:auto; }
  .filter { display:flex; align-items:center; gap:6px; }
  .filter label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  select { background:var(--bg); color:var(--fg); border:1px solid var(--line); border-radius:6px;
           padding:5px 8px; font:inherit; }
  main { padding:16px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:14px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden;
          cursor:pointer; transition:border-color .15s, transform .15s; }
  .card:hover { border-color:var(--accent); transform:translateY(-2px); }
  .thumb { aspect-ratio:9/16; display:flex; align-items:center; justify-content:center; background:
           conic-gradient(#1b2029 25%, #20262f 0 50%, #1b2029 0 75%, #20262f 0) 0 0/22px 22px; }
  .thumb img { max-width:100%; max-height:100%; object-fit:contain; display:block; }
  .meta { padding:7px 9px; font-size:11px; color:var(--muted); border-top:1px solid var(--line);
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .meta b { color:var(--fg); font-weight:600; }
  .tag { display:inline-block; font-size:10px; padding:1px 6px; border-radius:99px; border:1px solid var(--line);
         margin-right:4px; }
  .empty { color:var(--muted); padding:40px; text-align:center; }

  /* Lightbox */
  #lb { position:fixed; inset:0; z-index:20; background:rgba(6,8,12,.92); display:none;
        align-items:center; justify-content:center; }
  #lb.open { display:flex; }
  #lb .stage { max-width:92vw; max-height:82vh; display:flex; align-items:center; justify-content:center;
        background:conic-gradient(#1b2029 25%, #20262f 0 50%, #1b2029 0 75%, #20262f 0) 0 0/26px 26px;
        border-radius:8px; }
  #lb img { max-width:92vw; max-height:82vh; object-fit:contain; display:block; }
  #lb .cap { position:fixed; bottom:18px; left:50%; transform:translateX(-50%); color:var(--fg);
        background:var(--panel); border:1px solid var(--line); padding:7px 14px; border-radius:8px;
        font-size:13px; max-width:90vw; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  #lb .cap .muted { color:var(--muted); }
  .navbtn { position:fixed; top:50%; transform:translateY(-50%); width:54px; height:54px; border-radius:50%;
        border:1px solid var(--line); background:var(--panel); color:var(--fg); font-size:26px; cursor:pointer;
        display:flex; align-items:center; justify-content:center; user-select:none; }
  .navbtn:hover { border-color:var(--accent); }
  #prev { left:18px; } #next { right:18px; }
  #close { position:fixed; top:16px; right:18px; width:40px; height:40px; border-radius:8px; border:1px solid var(--line);
        background:var(--panel); color:var(--fg); font-size:20px; cursor:pointer; }
</style>
</head>
<body>
<header>
  <h1>Screenshot Builder</h1>
  <div class="filter"><label>Brand</label><select id="f-brand"></select></div>
  <div class="filter"><label>Platform</label><select id="f-platform"></select></div>
  <div class="filter"><label>Language</label><select id="f-lang"></select></div>
  <div class="filter"><label>Variant</label><select id="f-variant"></select></div>
  <div class="count" id="count"></div>
</header>
<main><div class="grid" id="grid"></div><div class="empty" id="empty" style="display:none">No images match these filters.</div></main>

<div id="lb">
  <button id="close" title="Close (Esc)">✕</button>
  <button class="navbtn" id="prev" title="Previous (←)">‹</button>
  <div class="stage"><img id="lb-img" alt=""></div>
  <button class="navbtn" id="next" title="Next (→)">›</button>
  <div class="cap" id="lb-cap"></div>
</div>

<script>
const IMAGES = /*__DATA__*/;
const OSLABEL = { ios:"iOS", android:"Android", other:"Other" };
const platformLabel = d => (OSLABEL[d.os] || d.os) + " " + d.form;

const $ = s => document.querySelector(s);
const grid = $("#grid"), empty = $("#empty"), countEl = $("#count");
let view = [];        // currently filtered list
let current = 0;      // index into view, for lightbox

function uniqueSorted(getter) {
  return [...new Set(IMAGES.map(getter))].sort();
}
function fillSelect(sel, values, allLabel) {
  sel.innerHTML = "";
  const optAll = document.createElement("option");
  optAll.value = ""; optAll.textContent = allLabel;
  sel.appendChild(optAll);
  for (const v of values) {
    const o = document.createElement("option");
    o.value = v.value !== undefined ? v.value : v;
    o.textContent = v.label !== undefined ? v.label : v;
    sel.appendChild(o);
  }
}
fillSelect($("#f-brand"), uniqueSorted(d => d.brand), "All brands");
fillSelect($("#f-platform"),
  [...new Map(IMAGES.map(d => [d.os+"/"+d.form, {value:d.os+"/"+d.form, label:platformLabel(d)}])).values()]
    .sort((a,b)=>a.label.localeCompare(b.label)), "All platforms");
fillSelect($("#f-lang"), uniqueSorted(d => d.lang), "All languages");
fillSelect($("#f-variant"), uniqueSorted(d => d.variant), "All variants");

function applyFilters() {
  const b = $("#f-brand").value, p = $("#f-platform").value,
        l = $("#f-lang").value, v = $("#f-variant").value;
  view = IMAGES.filter(d =>
    (!b || d.brand === b) &&
    (!p || (d.os+"/"+d.form) === p) &&
    (!l || d.lang === l) &&
    (!v || d.variant === v));
  render();
}

function render() {
  grid.innerHTML = "";
  countEl.textContent = view.length + " / " + IMAGES.length + " image" + (IMAGES.length===1?"":"s");
  empty.style.display = view.length ? "none" : "block";
  view.forEach((d, i) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML =
      '<div class="thumb"><img loading="lazy" src="'+d.src+'" alt=""></div>' +
      '<div class="meta"><span class="tag">'+platformLabel(d)+'</span>'+
      '<span class="tag">'+d.lang+'</span>'+
      (d.variant==="Clean" ? '<span class="tag">Clean</span>' : '')+
      '<br><b>'+d.file+'</b></div>';
    card.addEventListener("click", () => openLightbox(i));
    grid.appendChild(card);
  });
}

const lb = $("#lb"), lbImg = $("#lb-img"), lbCap = $("#lb-cap");
function openLightbox(i) { current = i; showCurrent(); lb.classList.add("open"); }
function closeLightbox() { lb.classList.remove("open"); }
function showCurrent() {
  if (!view.length) return;
  current = (current + view.length) % view.length;
  const d = view[current];
  lbImg.src = d.src;
  lbCap.innerHTML = '<b>'+d.brand+'</b> &nbsp;<span class="muted">'+platformLabel(d)+
    ' · '+d.lang+' · '+d.variant+' · '+d.w+'×'+d.h+'</span> &nbsp; '+d.file+
    ' &nbsp;<span class="muted">('+(current+1)+' / '+view.length+')</span>';
}
function step(n) { current += n; showCurrent(); }

$("#prev").addEventListener("click", e => { e.stopPropagation(); step(-1); });
$("#next").addEventListener("click", e => { e.stopPropagation(); step(1); });
$("#close").addEventListener("click", closeLightbox);
// Click left/right half of the image to navigate; click backdrop to close.
lb.addEventListener("click", e => {
  if (e.target === lb) { closeLightbox(); return; }
  if (e.target === lbImg) { step(e.offsetX < lbImg.clientWidth/2 ? -1 : 1); }
});
document.addEventListener("keydown", e => {
  if (!lb.classList.contains("open")) return;
  if (e.key === "ArrowLeft") step(-1);
  else if (e.key === "ArrowRight") step(1);
  else if (e.key === "Escape") closeLightbox();
});

for (const id of ["#f-brand","#f-platform","#f-lang","#f-variant"])
  $(id).addEventListener("change", applyFilters);

applyFilters();
</script>
</body>
</html>
"""
