from pathlib import Path
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

OUTPUT = Path(__file__).parent
NODES = {
    'input': ('User interface · Browser', 'Enter request → Analyze intent', 'frontend'),
    'intent': ('Intent parsing · Python backend', 'Call selected model; validate output\nExtract intent, targets, ingredients and preferences', 'backend'),
    'llm': ('Model APIs', 'OpenAI / DeepSeek: direct\nJev: via AI Gateway', 'external'),
    'edit': ('Review and edit · Browser', 'Inspect interpretation; edit query, filters and preferences\nClick Retrieval', 'frontend'),
    'prepare': ('Retrieval preparation · Python backend', 'Build text / label-scope plan and shared hard filters\nVector embeds semantic query; dispatch branches in parallel', 'backend'),
    'bm25': ('BM25 retrieval', 'Text relevance + shared filters', 'backend'),
    'vector': ('Vector retrieval', 'Local BGE embedding → kNN + shared filters', 'backend'),
    'es': ('Elasticsearch', 'Recipe data + vector index', 'external'),
    'rank': ('Fusion and reranking · Python backend', 'Weighted RRF + recipe-ID deduplication\nPreference adjustments + Rating bonus → Top results', 'backend'),
    'results': ('Results · Browser', 'Recipe cards and details\nRank explanations + stage timings', 'frontend'),
}
EDGES = [
    ('input', 'intent', 'Request + selected model'),
    ('intent', 'llm', 'Model request'),
    ('llm', 'intent', 'Model output'),
    ('intent', 'edit', 'Validated interpretation / feedback'),
    ('edit', 'prepare', 'Query + filters + preferences + settings'),
    ('prepare', 'bm25', 'Query + filters'),
    ('prepare', 'vector', 'Query + filters'),
    ('bm25', 'es', 'Text query'),
    ('vector', 'es', 'Vector query'),
    ('bm25', 'rank', 'Ranked candidates'),
    ('vector', 'rank', 'Ranked candidates'),
    ('rank', 'results', 'Recipes + scores + timings'),
]
COLORS = {'frontend':'#e9f2ff','backend':'#edf6ed','external':'#fff1d9','notes':'#f1f3f5'}
generation = '--generation' in sys.argv
basename = 'prototype-1.2-architecture' if generation else 'prototype-1.1-architecture'
heading = 'Prototype 1.2 — Recipe RAG Workflow' if generation else 'Prototype 1.1 — Current System Architecture / Information Flow\nImplemented baseline for Prototype 1.2 discussion'
if generation:
    NODES['prepare'] = ('Retrieval preparation · Python backend', 'Build positive editable queries + ingredient/numeric/manual filters\nMeal and cuisine boost recall only; parallel branches', 'backend')
    NODES['vector'] = ('Vector retrieval', 'Normalize main + beta scope embeddings\nOne kNN request with original ingredient/numeric/manual filters', 'backend')
    NODES['rank'] = ('Fusion and reranking · Python backend', 'Weighted RRF → Top 100 → Preference + Rating reranking\nReturn displayed results and ordered generation candidate IDs', 'backend')
    NODES['bm25'] = ('BM25 retrieval', 'Text match + ingredient, cuisine and meal boosts\nOriginal groups → any required → no required; retain strict hits', 'backend')
    NODES['input'] = ('Your request · Browser', 'Submit → Intent Analysis card', 'frontend')
    NODES['edit'] = ('Data Retrieval card · Browser', 'Edit independent queries + AND/OR required logic\nOriginal hard conditions remain the final eligibility standard', 'frontend')
    NODES['results'] = ('Retrieved recipes · Browser', 'Recipe cards, rank evidence and timings\nContent Generate becomes available', 'frontend')
    NODES['generate'] = ('Generation · Python backend', 'Read ordered RRF Top 100 IDs from ES\nAll local checks + pending semantic batches of 20\nBroad required cuisine confirmed; meal explanation only\nStop at 20–50 pass → pass-only summary', 'backend')
    NODES['model'] = ('Generation model API', 'OpenAI / DeepSeek · independent model selection', 'external')
    NODES['answer'] = ('Content Generate card · Browser', 'Grounded recommendations + clickable recipe details\nUnknown / fail / not_checked separate\nAll checks, model usage and timing available', 'frontend')
    EDGES += [('results','generate','Generate: query + intent + actual retrieval settings + Top 100 IDs'),
              ('generate','es','Batch read stored recipes'), ('generate','model','Pending semantic conditions only; then qualified recipe context'),
              ('model','generate','Structured assessments + recommendations'), ('generate','answer','Validated content + diagnostics')]

def dot_quote(value):
    return json.dumps(value, ensure_ascii=False)

dot_lines = ['digraph architecture {',
    f'graph [rankdir=TB, bgcolor="white", pad=0.35, nodesep=0.5, ranksep=0.65, fontname="Arial", labelloc=t, label={dot_quote(heading)}, fontsize=23];',
    'node [shape=box, style="rounded,filled", fontname="Arial", fontsize=12, margin="0.20,0.14", color="#8292a4", penwidth=1.2];',
    'edge [fontname="Arial", fontsize=10, color="#66768a", arrowsize=0.7];']
for identifier, (title, body, layer) in NODES.items():
    label = title + '\n\n' + body
    dot_lines.append(f'{identifier} [label={dot_quote(label)}, fillcolor="{COLORS[layer]}"];')
for source, target, label in EDGES:
    dot_lines.append(f'{source} -> {target} [label={dot_quote(label)}];')
dot_lines.extend(['{rank=same; intent; llm;}', '{rank=same; bm25; vector;}', '{rank=same; es; rank;}', *(['{rank=same; generate; model;}'] if generation else []), '}'])
dot_source = '\n'.join(dot_lines)
(OUTPUT / (basename+'.dot')).write_text(dot_source)
for extension in ('svg', 'png', 'json'):
    subprocess.run(['dot', '-T'+extension, str(OUTPUT / (basename+'.dot')), '-o', str(OUTPUT / (basename+'.'+extension))], check=True)
layout = json.loads((OUTPUT / (basename+'.json')).read_text())
left, bottom, right, top = map(float, layout['bb'].split(','))
document = ET.Element('mxfile', host='app.diagrams.net')
diagram = ET.SubElement(document, 'diagram', id=basename, name='1.2 Recipe RAG' if generation else '1.1 Current Architecture')
model = ET.SubElement(diagram, 'mxGraphModel', dx='1600', dy='1000', grid='1', gridSize='10', page='1', pageWidth=str(int(right+80)), pageHeight=str(int(top+120)))
root = ET.SubElement(model,'root')
ET.SubElement(root,'mxCell',id='0')
ET.SubElement(root,'mxCell',id='1',parent='0')
title_cell = ET.SubElement(root,'mxCell',id='title',value=heading,style='text;html=0;align=center;verticalAlign=middle;fontSize=23;fontStyle=1;',vertex='1',parent='1')
ET.SubElement(title_cell,'mxGeometry',x='20',y='0',width=str(right+40),height='70',attrib={'as':'geometry'})
for node in layout['objects']:
    identifier = node['name']
    if identifier not in NODES:
        continue
    title, body, layer = NODES[identifier]
    center_x, center_y = map(float,node['pos'].split(','))
    width, height = float(node['width'])*72, float(node['height'])*72
    cell = ET.SubElement(root,'mxCell',id=identifier,value=title+'\n\n'+body,style=f'rounded=1;whiteSpace=wrap;html=0;fillColor={COLORS[layer]};strokeColor=#8292a4;fontFamily=Arial;fontSize=12;align=center;verticalAlign=middle;spacing=10;',vertex='1',parent='1')
    ET.SubElement(cell,'mxGeometry',x=str(center_x-width/2+40),y=str(top-center_y-height/2+40),width=str(width),height=str(height),attrib={'as':'geometry'})
for index, edge in enumerate(layout['edges']):
    source = layout['objects'][edge['tail']]['name']
    target = layout['objects'][edge['head']]['name']
    if (source,target) not in {(a,b) for a,b,_ in EDGES}:
        continue
    cell = ET.SubElement(root,'mxCell',id=f'edge-{index}',value=edge.get('label',''),style='edgeStyle=none;rounded=0;html=0;endArrow=block;endFill=1;strokeColor=#66768a;fontSize=10;fontFamily=Arial;labelBackgroundColor=#ffffff;',edge='1',parent='1',source=source,target=target)
    geometry = ET.SubElement(cell,'mxGeometry',relative='1',attrib={'as':'geometry'})
    points = ET.SubElement(geometry,'Array',attrib={'as':'points'})
    for drawing in edge.get('_draw_',[]):
        if drawing['op']=='b':
            for point_x,point_y in drawing['points'][1:-1]:
                ET.SubElement(points,'mxPoint',x=str(point_x+40),y=str(top-point_y+40))
ET.indent(document)
ET.ElementTree(document).write(OUTPUT/(basename+'.drawio'),encoding='utf-8',xml_declaration=True)
print(f'Generated editable draw.io source and SVG/PNG previews: {len(NODES)} nodes, {len(EDGES)} connections')
