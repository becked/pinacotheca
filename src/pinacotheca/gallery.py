"""
HTML gallery generator for extracted sprites.

Generates an interactive, searchable gallery with lightbox viewing.
"""

from pathlib import Path

from pinacotheca.categories import get_category_display

# Default paths
DEFAULT_OUTPUT_DIR = Path.cwd() / "extracted"


def generate_gallery(output_dir: Path | None = None, *, verbose: bool = True) -> Path | None:
    """
    Generate an HTML gallery from extracted sprites.

    Args:
        output_dir: Directory containing sprites/ subdirectory
        verbose: Print progress messages

    Returns:
        Path to generated gallery.html, or None if no sprites found
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    sprites_dir = output_dir / "sprites"
    if not sprites_dir.exists():
        if verbose:
            print(f"ERROR: Sprites directory not found: {sprites_dir}")
            print("Run extraction first.")
        return None

    if verbose:
        print("Generating gallery...")

    # Collect sprites by category
    categories: dict[str, list[str]] = {}
    for cat_dir in sorted(sprites_dir.iterdir()):
        if cat_dir.is_dir():
            sprites = sorted([f.name for f in cat_dir.glob("*.png")])
            if sprites:
                categories[cat_dir.name] = sprites

    if not categories:
        if verbose:
            print("No sprites found!")
        return None

    total = sum(len(s) for s in categories.values())

    # Build HTML
    nav_html = ""
    sections_html = ""

    for cat_id, sprites in categories.items():
        name, icon = get_category_display(cat_id)
        count = len(sprites)

        nav_html += (
            f'<a href="#" class="nav-item" data-category="{cat_id}">'
            f'<span class="icon">{icon}</span>'
            f'<span class="name">{name}</span>'
            f'<span class="count">{count}</span>'
            f"</a>\n"
        )

        images = "\n".join(
            [
                f'<div class="sprite" title="{s}">'
                f'<img src="sprites/{cat_id}/{s}" loading="lazy">'
                f'<span class="label">{s[:-4]}</span>'
                f"</div>"
                for s in sprites
            ]
        )
        sections_html += (
            f'<section id="{cat_id}" class="category-section">'
            f"<h2>{icon} {name} "
            f'<span class="section-count">({count})</span></h2>'
            f'<div class="sprite-grid">{images}</div>'
            f"</section>\n"
        )

    html = _generate_html_template(nav_html, sections_html, total)

    # For GitHub Pages, output as index.html
    gallery_path = output_dir / "index.html"
    gallery_path.write_text(html)

    # Also create gallery.html as symlink/copy for backwards compatibility
    legacy_path = output_dir / "gallery.html"
    if not legacy_path.exists():
        legacy_path.write_text(html)

    if verbose:
        print(f"Gallery saved to: {gallery_path}")

    return gallery_path


def _generate_html_template(nav_html: str, sections_html: str, total: int) -> str:
    """Generate the complete HTML document."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Old World Sprites Gallery</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#1a1a2e;color:#eee;display:flex;min-height:100vh}}
.sidebar{{width:240px;background:#16213e;padding:20px 0;position:fixed;height:100vh;overflow-y:auto;border-right:1px solid #0f3460}}
.sidebar h1{{font-size:1.2rem;padding:0 20px 15px;border-bottom:1px solid #0f3460;margin-bottom:15px}}
.sidebar h1 small{{display:block;font-weight:normal;font-size:0.75rem;color:#888;margin-top:5px}}
.nav-item{{display:flex;align-items:center;padding:10px 20px;color:#aaa;text-decoration:none;transition:all 0.2s;cursor:pointer}}
.nav-item:hover{{background:#0f3460;color:#fff}}
.nav-item.active{{background:#e94560;color:#fff}}
.nav-item .icon{{width:24px;text-align:center;margin-right:10px}}
.nav-item .name{{flex:1}}
.nav-item .count{{background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:10px;font-size:0.75rem}}
.main{{flex:1;margin-left:240px;padding:30px}}
.search-container{{position:sticky;top:0;background:#1a1a2e;padding:15px 0;margin-bottom:20px;z-index:100}}
.search-input{{width:100%;max-width:400px;padding:12px 20px;border:2px solid #0f3460;border-radius:25px;background:#16213e;color:#fff;font-size:1rem}}
.search-input:focus{{outline:none;border-color:#e94560}}
.category-section{{margin-bottom:40px}}
.category-section h2{{font-size:1.5rem;margin-bottom:20px;padding-bottom:10px;border-bottom:2px solid #0f3460}}
.section-count{{font-weight:normal;color:#888;font-size:1rem}}
.sprite-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:15px}}
.sprite{{background:#16213e;border-radius:8px;padding:10px;text-align:center;transition:transform 0.2s,box-shadow 0.2s;cursor:pointer}}
.sprite:hover{{transform:translateY(-5px);box-shadow:0 10px 30px rgba(0,0,0,0.3)}}
.sprite img{{max-width:100%;max-height:100px;object-fit:contain;image-rendering:pixelated}}
.sprite .label{{display:block;margin-top:8px;font-size:0.7rem;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.sprite.hidden{{display:none}}
.lightbox{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:1000;justify-content:center;align-items:center;flex-direction:column}}
.lightbox.active{{display:flex}}
.lightbox img{{max-width:90%;max-height:80%;image-rendering:pixelated}}
.lightbox .caption{{margin-top:20px;font-size:1.2rem}}
.lightbox .close{{position:absolute;top:20px;right:30px;font-size:2rem;cursor:pointer;color:#fff}}
@media(max-width:768px){{.sidebar{{width:100%;height:auto;position:relative;border-right:none;border-bottom:1px solid #0f3460}}.main{{margin-left:0}}.sprite-grid{{grid-template-columns:repeat(auto-fill,minmax(80px,1fr))}}}}
</style>
</head>
<body>
<nav class="sidebar">
<h1>Old World Sprites<small>{total:,} images extracted</small></h1>
{nav_html}
</nav>
<main class="main">
<div class="search-container"><input type="text" class="search-input" placeholder="Search sprites..." id="search"></div>
{sections_html}
</main>
<div class="lightbox" id="lightbox"><span class="close">&times;</span><img src="" alt=""><div class="caption"></div></div>
<script>
document.querySelectorAll('.nav-item').forEach(item=>{{item.addEventListener('click',e=>{{e.preventDefault();const cat=item.dataset.category;const sec=document.getElementById(cat);if(sec)sec.scrollIntoView({{behavior:'smooth'}});document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));item.classList.add('active')}});}});
document.getElementById('search').addEventListener('input',e=>{{const q=e.target.value.toLowerCase();document.querySelectorAll('.sprite').forEach(s=>{{s.classList.toggle('hidden',!s.getAttribute('title').toLowerCase().includes(q))}});}});
const lb=document.getElementById('lightbox'),lbImg=lb.querySelector('img'),lbCap=lb.querySelector('.caption');
document.querySelectorAll('.sprite').forEach(s=>{{s.addEventListener('click',()=>{{lbImg.src=s.querySelector('img').src;lbCap.textContent=s.getAttribute('title');lb.classList.add('active')}});}});
lb.addEventListener('click',e=>{{if(e.target===lb||e.target.classList.contains('close'))lb.classList.remove('active')}});
document.addEventListener('keydown',e=>{{if(e.key==='Escape')lb.classList.remove('active')}});
</script>
</body>
</html>"""
