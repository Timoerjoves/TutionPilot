"""Text out of an uploaded PDF invoice, standard library only.

Reads text drawn with the PDF text operators (Tj, TJ, ', ") from plain or Flate-compressed content streams,
including PDF 1.5 object streams, decodes embedded fonts through their ToUnicode maps, and rebuilds lines by
position. Pieces placed separately on one line are joined with a tab, so "Label<tab>value" reads like "Label: value".

shortcut: no OCR (a scanned invoice is a picture with no text), no encrypted PDFs, and approximate positions
(the page transform `cm` is ignored); upgrade to a vetted parser such as pypdf if real invoices need it.
The PDF is untrusted input: sizes are capped before and after decompression.
"""
import base64
import binascii
import re
import zlib

MAX_PDF_BYTES = 2 * 1024 * 1024
MAX_INFLATED = 20 * 1024 * 1024  # all streams together, unpacked: stops a zip bomb

OBJ = re.compile(rb"(\d+)\s+\d+\s+obj\b(.*?)\bendobj", re.S)
STREAM = re.compile(rb"stream\r?\n(.*?)\r?\n?endstream", re.S)
REF = rb"\s+(\d+)\s+\d+\s+R"
TOKEN = re.compile(rb"\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\)"   # literal string, one level of nesting
                   rb"|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/<>\[\]()]+"      # hex string, array brackets, name
                   rb"|[-+]?(?:\d+\.?\d*|\.\d+)|[A-Za-z'\"*]+")     # number, operator
ESC = re.compile(rb"\\([nrtbf()\\]|[0-7]{1,3}|\r?\n)")
ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


class PdfError(ValueError):
    pass


def pdf_to_text(data):
    """PDF bytes -> invoice text, one line per printed line. Raises PdfError when nothing readable is found."""
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("the PDF is larger than 2 MB")
    if not data.startswith(b"%PDF-"):
        raise PdfError("that file is not a PDF")
    if b"/Encrypt" in data:
        raise PdfError("the PDF is password-protected; upload an unprotected copy")
    objs = _objects(data)
    fonts = _fonts(objs)
    lines = []
    for body, stream in objs.values():
        if stream and b"BT" in stream and b"begincmap" not in stream:
            lines += _lines(stream, fonts)
    text = "\n".join(l for l in lines if l.strip())
    if not text.strip():
        raise PdfError("this PDF has no readable text (it may be a scanned image); upload a text PDF or type the details")
    return text


# ---------- objects and streams ----------
def _inflate(raw, budget):
    try:
        out = zlib.decompressobj().decompress(raw, budget[0] + 1)
    except zlib.error:
        return None
    if len(out) > budget[0]:
        raise PdfError("the PDF unpacks to more than 20 MB")
    budget[0] -= len(out)
    return out


def _objects(data):
    """{object number: (dictionary bytes, decoded stream or None)}, including objects packed in object streams."""
    out, budget = {}, [MAX_INFLATED]
    for m in OBJ.finditer(data):
        body, stream = m.group(2), None
        s = STREAM.search(body)
        if s:
            head, raw = body[:s.start()], s.group(1)
            if b"/ASCII85Decode" in head:  # ReportLab wraps its streams in ASCII85 before Flate
                try:
                    raw = base64.a85decode(raw.strip(), adobe=True)
                except (ValueError, binascii.Error):
                    raw = None
            filters = set(re.findall(rb"/(\w+Decode)", head)) - {b"ASCII85Decode"}
            if raw is not None and filters == {b"FlateDecode"}:
                stream = _inflate(raw, budget)
            elif raw is not None and not filters:
                stream = raw
            body = head
        out[int(m.group(1))] = (body, stream)
        first = re.search(rb"/First\s+(\d+)", body)
        if stream and b"/ObjStm" in body and first:
            nums = stream[:int(first.group(1))].split()
            pairs = [(int(nums[i]), int(first.group(1)) + int(nums[i + 1])) for i in range(0, len(nums) - 1, 2)]
            for i, (num, start) in enumerate(pairs):
                end = pairs[i + 1][1] if i + 1 < len(pairs) else len(stream)
                out.setdefault(num, (stream[start:end], None))
    return out


# ---------- fonts ----------
def _fonts(objs):
    """{font resource name: (ToUnicode map, code width in bytes)} for fonts that carry one."""
    named = {}
    for body, _ in objs.values():
        for inline in re.findall(rb"/Font\s*<<(.*?)>>", body, re.S):
            named.update(re.findall(rb"/([^\s/<>\[\]()]+)" + REF, inline))
        for ref in re.findall(rb"/Font" + REF, body):
            named.update(re.findall(rb"/([^\s/<>\[\]()]+)" + REF, objs.get(int(ref), (b"", None))[0]))
    fonts = {}
    for name, ref in named.items():  # shortcut: one map per resource name, even if pages reuse a name
        to_unicode = re.search(rb"/ToUnicode" + REF, objs.get(int(ref), (b"", None))[0])
        cmap = to_unicode and objs.get(int(to_unicode.group(1)), (b"", None))[1]
        if cmap:
            fonts[name] = _cmap(cmap)
    return fonts


def _utf16(hexdigits):
    return bytes.fromhex(hexdigits.decode()).decode("utf-16-be", "replace")


def _cmap(data):
    width = 2 if re.search(rb"begincodespacerange\s*<[0-9A-Fa-f]{4}>", data) else 1
    m = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            m[bytes.fromhex(src.decode())] = _utf16(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", block):
            a, b, n = int(lo, 16), int(hi, 16), len(lo) // 2
            if dst.startswith(b"["):
                for i, d in enumerate(re.findall(rb"<([0-9A-Fa-f]+)>", dst)):
                    m[(a + i).to_bytes(n, "big")] = _utf16(d)
            else:
                start, digits = int(dst[1:-1], 16), len(dst) - 2
                for i in range(min(b - a + 1, 65536)):
                    m[(a + i).to_bytes(n, "big")] = _utf16(format(start + i, f"0{digits}x").encode())
    return m, width


def _decode(tok, font):
    if tok[:1] == b"<":
        digits = re.sub(rb"\s", b"", tok[1:-1])
        raw = bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode())
    else:
        raw = ESC.sub(lambda m: bytes([int(m.group(1), 8) & 255]) if m.group(1)[:1].isdigit()
                      else ESCAPES.get(m.group(1), b"" if not m.group(1).strip() else m.group(1)), tok[1:-1])
    if font:
        m, w = font
        return "".join(m.get(raw[i:i + w], "") for i in range(0, len(raw), w))
    return raw.decode("cp1252", "replace")


# ---------- text placement ----------
def _num(tok):
    try:
        return float(tok)
    except ValueError:
        return 0.0


def _lines(content, fonts):
    """Show operators -> lines, top to bottom; separately placed pieces on one line joined with a tab."""
    segs, ops = [], []
    lx = ly = lead = 0.0
    font, moved = None, True
    for t in TOKEN.findall(content):
        if t[:1] in b"(<[]/" or t[:1].isdigit() or t[:1] in b"-+.":
            ops.append(t)
            continue
        if t == b"Tf" and len(ops) >= 2:
            font = fonts.get(ops[-2][1:])
        elif t == b"TL" and ops:
            lead = _num(ops[-1])
        elif t == b"Tm" and len(ops) >= 6:
            lx, ly, moved = _num(ops[-2]), _num(ops[-1]), True
        elif t in (b"Td", b"TD") and len(ops) >= 2:
            lx, ly, moved = lx + _num(ops[-2]), ly + _num(ops[-1]), True
            if t == b"TD":
                lead = -_num(ops[-1])
        elif t == b"T*":
            ly, moved = ly - lead, True
        elif t == b"BT":
            lx = ly = 0.0
            moved = True
        elif t in (b"Tj", b"TJ", b"'", b'"'):
            if t in (b"'", b'"'):
                ly, moved = ly - lead, True
            text = ""
            for o in ops:
                if o[:1] in b"(<":
                    text += _decode(o, font)
                elif t == b"TJ" and o[:1] not in b"[]/" and _num(o) < -200:
                    text += " "  # a wide kerning gap inside TJ is a word space
            if text:
                if not moved and segs and segs[-1][0] == round(ly):
                    segs[-1][3] += text
                else:
                    segs.append([round(ly), lx, len(segs), text])
                moved = False
        ops = []
    lines = []
    for seg in sorted(segs, key=lambda s: (-s[0], s[1], s[2])):
        if lines and abs(lines[-1][0] - seg[0]) <= 2:
            lines[-1][1].append(seg[3].strip())
        else:
            lines.append([seg[0], [seg[3].strip()]])
    return ["\t".join(p for p in parts if p) for _, parts in lines]
