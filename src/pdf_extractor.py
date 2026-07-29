import os
import pdfplumber

def extract_context(paths, max_chars=40000):
    if not paths: return ""
    chunks, budget = [], max_chars
    for p in paths:
        if not os.path.exists(p): continue
        try:
            with pdfplumber.open(p) as pdf:
                text = []
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    text.append(t)
                    if sum(len(x) for x in text) > budget: break
                body = "\n".join(text)[:budget]
        except Exception as e:
            body = f"[unavailable: {e}]"
        tag = f"\n===== SOURCE: {os.path.basename(p)} =====\n"
        piece = (tag + body)[:budget]
        chunks.append(piece)
        budget -= len(piece)
        if budget <= 0: break
    return "".join(chunks)[:max_chars + 200]
