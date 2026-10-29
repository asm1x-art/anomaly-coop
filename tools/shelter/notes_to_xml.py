# notes_to_xml.py <SHETER ZOMBIE.md> <out.xml>: the Brigadier's and the Chemist's PDA notes as a cp1251 string table
# (st_shelter_note_<who>_<n>_title / _text), the md's markup cleaned, file remarks in brackets grey
import html
import re
import sys

src, out = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
text = text.replace("&#x20;", " ").replace("\r\n", "\n")
lines = [re.sub(r"\\([#*\[\]_>])", r"\1", l).rstrip() for l in text.split("\n")]

brig_end = next(i for i, l in enumerate(lines) if l.startswith("====="))
chem_archive = next(i for i, l in enumerate(lines) if "Заметки КПК Химика" in l)


def notes(start, end):
    found, cur = [], None
    for l in lines[start:end]:
        m = re.match(r"^###\s*Заметка\s*(\d+)\.\s*(.*)$", l)
        if m:
            cur = {"n": int(m.group(1)), "title": "Заметка %s. %s" % (m.group(1), m.group(2).strip()), "body": []}
            found.append(cur)
        elif l.startswith("#"):
            cur = None  # a heading of the design notes: not a PDA's
        elif cur is not None:
            cur["body"].append(re.sub(r"^\s*>\s?", "", l))
    for n in found:
        paras, para = [], []
        for l in n["body"] + [""]:
            if l.strip():
                para.append(l.strip())
            elif para:
                paras.append(" ".join(para))
                para = []
        n["paras"] = paras
    return found


brigadier = notes(0, brig_end)
chemist = notes(brig_end, chem_archive)[:1] + notes(chem_archive, len(lines))  # its note 0, then the archive


def body(paras):
    res = []
    for p in paras:
        # a remark of the file itself ("*[Файл повреждён...]*"): grey
        p = re.sub(r"\*?\[([^\]]+)\]\*?", lambda m: "%c[0,140,140,140][" + m.group(1) + "]%c[0,210,210,210]", p)
        res.append(p.replace("*", ""))
    return "%c[0,210,210,210]" + "\\n\\n".join(res)


rows = []
for who, ns in (("brigadier", brigadier), ("chemist", chemist)):
    for n in ns:
        key = "st_shelter_note_%s_%d" % (who, n["n"])
        rows.append((key + "_title", n["title"]))
        rows.append((key + "_text", body(n["paras"])))
xml = ['<?xml version="1.0" encoding="windows-1251"?>', "",
       "<!-- The Brigadier's and the Chemist's PDA notes (the PDA's Base tab, ui_pda_shelter_base.script), made by",
       "     notes_to_xml.py from the author's SHETER ZOMBIE.md -->",
       "<string_table>"]
for k, v in rows:
    xml.append('\t<string id="%s">' % k)
    xml.append("\t\t<text>%s</text>" % html.escape(v, quote=False))
    xml.append("\t</string>")
xml.append("</string_table>")
data = "\r\n".join(xml) + "\r\n"
bad = sorted({c for c in data if c not in "\r\n" and not c.encode("cp1251", "ignore")})
open(out, "wb").write(data.encode("cp1251", "replace"))
print("brigadier", [n["n"] for n in brigadier], "chemist", [n["n"] for n in chemist], "not in cp1251:", bad)
for who, ns in (("brigadier", brigadier), ("chemist", chemist)):
    for n in ns:
        print(who, n["title"], len(n["paras"]), "paras,", sum(len(p) for p in n["paras"]), "chars")
