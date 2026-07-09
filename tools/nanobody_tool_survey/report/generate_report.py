#!/usr/bin/env python3
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'report'
META = ROOT / 'metadata'
REPORT.mkdir(parents=True, exist_ok=True)
assets = json.load(open(META / 'asset_download_results.json', encoding='utf-8'))

pdf_counter = Counter()
code_counter = Counter()
for item in assets:
    for p in item.get('paper_downloads', []):
        pdf_counter[p.get('status')] += 1
    for c in item.get('code_downloads', []):
        code_counter[c.get('status')] += 1

pdf_files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'papers').rglob('*.pdf'))
repo_dirs = sorted(str(p.parent.relative_to(ROOT)) for p in (ROOT / 'code').rglob('.git'))

TIER = {
    # A: local code plus public weights or no neural weights; start here for reproducible local work.
    'nanobodybuilder2_immunebuilder': 'A 开源可复现优先',
    'heavybuilder2': 'A 开源可复现优先',
    'haddock3': 'A 开源可复现优先',
    'chai1': 'A 开源可复现优先',
    'boltz': 'A 开源可复现优先',
    'rfantibody': 'A 开源可复现优先',
    'antifold': 'A 开源可复现优先',
    'iggm': 'A 开源可复现优先',
    'biophi': 'A 开源可复现优先',
    'humatch': 'A 开源可复现优先',
    'alpseq': 'A 开源可复现优先',
    'phage_seq_nbseq': 'A 开源可复现优先',
    'anarci': 'A 开源可复现优先',
    'immcantation': 'A 开源可复现优先',
    'deepnano': 'A 开源可复现优先',
    'paragraph': 'A 开源可复现优先',
    'tnp': 'A 开源可复现优先',
    'protparam': 'A 基础可复现/网页',
    # B: code exists, but license, weights, large external dependencies, or non-VHH calibration mean second pass.
    'nanonet': 'B 可用但许可/商业需确认',
    'igfold': 'B 学术许可/非完全开放',
    'abodybuilder3': 'B 非VHH主线/补充',
    'deepab': 'B 非VHH主线/补充',
    'ablooper': 'B CDR loop补充',
    'h3_opt': 'B CDR-H3补充',
    'alphafold3': 'B 权重/条款受限',
    'colabfold_alphafold_multimer': 'B AF参数/条款需记录',
    'balmfold': 'B 通用模型/补充',
    'abdockgen': 'B docking生成补充',
    'deeprank_ab': 'B docking排序补充',
    'nanodesigner': 'B 外部依赖较多',
    'germinal': 'B PyRosetta/AF依赖',
    'diffab': 'B 非VHH主线/需适配',
    'iglm': 'B 学术许可/非VHH专用',
    'vhhbert': 'B 数据许可/下游任务受限',
    'abnativ': 'B 非商业许可',
    'hudiff': 'B 非商业许可',
    'gearbind': 'B 非VHH专用ΔΔG',
    'graphinity': 'B 非VHH专用ΔΔG',
    'nanomap': 'B 非商业许可/新工具',
    'mixcr': 'B 许可证/自定义库',
    'igdiscover': 'B germline发现补充',
    'nabp_bert': 'B 序列级预测需验证',
    'abagintpre': 'B 非VHH专用预测',
    'parapred': 'B paratope补充',
    'episcan': 'B epitope补充',
    'imapeP': 'B epitope补充',
    # C: no local open code/weights in this package, mostly web, commercial, paper-only, or white paper.
    'rosetta_snugdock': 'C 外部软件/许可流程',
    'cluspro_abemap': 'C 网页/服务为主',
    'hdock': 'C 网页/服务为主',
    'tfdesign_sdab': 'C 论文为主/代码未获',
    'chai2': 'C 闭源/公司平台',
    'latentx2': 'C 论文/公司平台',
    'jam2': 'C 白皮书/公司平台',
    'easynano': 'C 预印本/代码未确认',
    'nanofold': 'C 预印本/代码未确认',
    'llamanade': 'C 方法重要但代码不明确',
    'mcsm_ab2': 'C 网页服务为主',
    'igblast': 'C 官方工具/未纳入本地代码',
    'sabpred_epipred': 'C 网页服务为主',
    'abadapt': 'C 网页workflow',
    'aggrescan3d': 'C 网页/standalone另取',
    'camsol': 'C 网页/外部工具',
    'iedb_netmhc': 'C 网页/外部工具',
    'tap': 'C 常规抗体网页工具',
    'protein_sol_abpred': 'C 网页/外部工具',
    'dynamut2': 'C 网页服务为主',
    'foldx': 'C 外部许可证/二进制',
    'solart': 'C 外部/商业或服务',
}

SCOPE = {
    'nanobodybuilder2_immunebuilder': 'VHH单体结构预测；批量建模、CDR3观察、docking前准备',
    'nanonet': 'VHH/VH快速结构预测；repertoire级粗建模',
    'igfold': '抗体/nanobody结构baseline；快速PDB生成',
    'heavybuilder2': '单heavy-chain结构建模；VHH/VH混合数据补充',
    'abodybuilder3': '常规VH/VL结构预测；VHH项目只作参考',
    'deepab': '历史抗体结构预测baseline；非VHH主线',
    'ablooper': 'CDR loop预测；修正局部loop而非完整复合物',
    'h3_opt': 'CDR-H3 loop优化；长CDR3局部精修参考',
    'rosetta_snugdock': '抗体/纳米抗体docking和refinement；高门槛',
    'alphafold3': 'all-atom复合物预测；VHH-Ag候选pose',
    'colabfold_alphafold_multimer': 'AF2多链复合物baseline；多seed互证',
    'chai1': '开放复合物/co-folding模型；VHH-Ag候选pose',
    'boltz': '开放AF3-like结构/复合物模型；可与Chai互证',
    'haddock3': '约束docking；把表位/突变/预测界面转成restraints',
    'cluspro_abemap': '网页docking/epitope候选；用于假设生成',
    'hdock': '网页protein-protein docking；快速候选pose',
    'balmfold': '通用结构模型；VHH补充baseline',
    'abdockgen': '抗体-抗原docking生成；研究对照',
    'deeprank_ab': 'docking pose排序；HADDOCK生态补充',
    'rfantibody': '表位条件de novo VHH/scFv设计；开源主线',
    'nanodesigner': 'VHH CDR设计/优化workflow；外部依赖多',
    'germinal': 'epitope-targeted VHH/scFv生成；RFantibody对照',
    'iggm': '抗体/nanobody结构-序列联合生成；多任务模型',
    'tfdesign_sdab': '单域抗体设计论文；本地不可复现优先级低',
    'chai2': '公司zero-shot抗体/VHH设计平台；了解前沿',
    'latentx2': 'all-atom生成平台；公司/论文方向',
    'jam2': 'Nabla VHH/mAb设计白皮书；了解benchmark设定',
    'easynano': 'epitope-targeted nanobody CDR设计预印本',
    'diffab': '抗原条件CDR diffusion；需适配VHH',
    'antifold': '结构条件inverse folding；VHH scaffold/CDR重设计',
    'nanofold': 'VHH inverse folding预印本；代码/权重未明确',
    'iglm': '抗体语言模型；序列生成/补全，非VHH专用',
    'vhhbert': 'VHH语言模型/embedding；下游binding和突变分析',
    'abnativ': 'nativeness/humanness；VHH hit selection和人源化风险',
    'hudiff': 'HuDiff-Nb人源化；保留结合前提下改造VHH',
    'llamanade': 'VHH人源化规则/结构方法；概念参考',
    'biophi': '人源化/humanness/OASis；VHH辅助参考',
    'humatch': 'human-likeness匹配；人源化辅助',
    'igcraft': '抗体生成/工程新工具；需进一步验证',
    'mcsm_ab2': 'Ab-Ag突变ΔΔG；有复合物时辅助亲和力成熟',
    'gearbind': '几何GNN突变/结合排序；非VHH专用',
    'graphinity': '等变GNN ΔΔG；研究框架/亲和力成熟辅助',
    'alpseq': 'VHH Illumina NGS pipeline；展示库/免疫库入口',
    'nanomap': 'VHH repertoire处理和clone family/富集分析',
    'phage_seq_nbseq': 'phage display NGS后处理和候选表',
    'anarci': '抗体编号/CDR定位；所有VHH流程基础',
    'igblast': 'VDJ/germline注释；需camelid自定义库',
    'mixcr': '大规模AIRR/BCR/TCR分析；需VHH库适配',
    'immcantation': 'AIRR-seq生态；clone/lineage/SHM分析',
    'igdiscover': 'germline发现；构建/校正VHH V基因库',
    'deepnano': 'Nb-Ag interaction sequence模型；候选预排序',
    'nabp_bert': 'Nb-Ag binding probability；序列级辅助筛选',
    'abagintpre': 'Ab-Ag interaction预测；非VHH专用baseline',
    'paragraph': '结构型paratope预测；给docking约束/突变假设',
    'parapred': '序列型paratope预测；非VHH专用',
    'sabpred_epipred': 'epitope/paratope网页workflow；假设生成',
    'abadapt': '抗体-抗原web workflow；建模+docking+预测',
    'episcan': '抗体特异epitope mapping；表位假设',
    'imapeP': 'paratope-epitope pair预测；表位辅助',
    'tnp': 'VHH developability profiler；性质预测主线',
    'aggrescan3d': '结构聚集patch；VHH表面疏水风险',
    'camsol': '溶解性profile；低溶解片段和突变建议',
    'protparam': 'Mw/pI/GRAVY等基础物化字段',
    'iedb_netmhc': 'MHC-II epitope/免疫原性风险筛查',
    'tap': '常规抗体developability；VHH只作对照',
    'protein_sol_abpred': 'sequence-level solubility/表达辅助',
    'dynamut2': '突变稳定性/柔性变化；结构依赖',
    'foldx': '经验势能ΔΔG；突变稳定性/界面能辅助',
    'solart': '结构型溶解性/聚集风险补充',
}

category_names = {
    'structure': '结构预测/复合物建模',
    'design': '设计/优化/人源化',
    'identification': '识别/发现/结合预测',
    'properties': '性质预测/可开发性',
}

inventory_lines = ['# 附录 A：本地下载清单\n']
inventory_lines.append('## A1. 成功下载的论文 PDF\n')
inventory_lines.extend(f'- `{p}`' for p in pdf_files) if pdf_files else inventory_lines.append('- 无')
inventory_lines.append('\n## A2. 成功浅克隆的代码仓库\n')
inventory_lines.extend(f'- `{p}`' for p in repo_dirs) if repo_dirs else inventory_lines.append('- 无')
inventory_lines.append('\n## A3. 每个工具的资产状态\n')
for item in assets:
    inventory_lines.append(f"### {item['name']} (`{item['id']}`)")
    inventory_lines.append(f"- 类别：{category_names.get(item['category'], item['category'])}")
    if item.get('paper_downloads'):
        for p in item['paper_downloads']:
            inventory_lines.append(f"- PDF：{p.get('status')} | `{p.get('path', '')}` | {p.get('url')}")
    else:
        inventory_lines.append('- PDF：无直接开放 PDF 候选或仅有网页/商业白皮书链接')
    if item.get('code_downloads'):
        for c in item['code_downloads']:
            inventory_lines.append(f"- Code：{c.get('status')} | `{c.get('path', '')}` | {c.get('url')}")
    else:
        inventory_lines.append('- Code：无公开代码仓库、Web only、商业闭源或需手动申请')
    inventory_lines.append('')
(REPORT / 'asset_inventory.md').write_text('\n'.join(inventory_lines), encoding='utf-8')

matrix_lines = [
    '### 1.3 全部工具速览矩阵（按可复现优先级）\n',
    '| 优先级 | 类别 | 工具 | 主要用途范围 | 本地代码 | PDF/论文状态 |',
    '|---|---|---|---|---|---|',
]
for item in assets:
    code_paths = [c.get('path', '') for c in item.get('code_downloads', []) if c.get('status') == 'cloned']
    paper_status = ', '.join(p.get('status', '') for p in item.get('paper_downloads', [])) or '无直接PDF候选'
    code_status = f'已克隆 {len(code_paths)} 个仓库' if code_paths else '无本地公开代码'
    matrix_lines.append(
        f"| {TIER.get(item['id'], 'B/C 待确认')} | {category_names.get(item['category'], item['category'])} | {item['name']} | {SCOPE.get(item['id'], '见对应章节或附录')} | {code_status} | {paper_status} |"
    )
(REPORT / 'reproducibility_matrix.md').write_text('\n'.join(matrix_lines), encoding='utf-8')

body_file = REPORT / 'tool_survey_body_v2.md'
body = body_file.read_text(encoding='utf-8')
matrix_text = '\n'.join(matrix_lines)
body = body.replace('\n---\n\n## 2. A 类：', '\n' + matrix_text + '\n\n---\n\n## 2. A 类：', 1)
header = f"""# 纳米抗体/VHH 工具全景调研报告（开源可复现优先版）

生成日期：2026-07-06  
工作目录：`{ROOT}`  
资料包目录：`nanobody_tool_survey/`

## 0. 本地资料包说明

这版报告根据你的反馈重排：**正文优先讲能公开获取代码/权重、能本地复现或至少能稳定使用的工具**；不能确认开源复现、只有网页/商业平台/论文白皮书的工具不删除，而是放到后置章节，作为了解和对照。

- 论文 PDF 目录：`nanobody_tool_survey/papers/`
- 代码目录：`nanobody_tool_survey/code/`
- 报告目录：`nanobody_tool_survey/report/`
- 下载日志与 manifest：`nanobody_tool_survey/metadata/`、`nanobody_tool_survey/logs/`
- 调研工具总数：{len(assets)} 个
- 成功下载 PDF：{len(pdf_files)} 个
- 成功浅克隆代码仓库：{len(repo_dirs)} 个
- PDF 下载状态统计：`{dict(pdf_counter)}`
- 代码下载状态统计：`{dict(code_counter)}`

阅读建议：

1. 先看第 1-2 章：这些是优先复现和优先理解的开源工具。
2. 再看第 3 章：这些工具有代码，但权重、许可证、依赖或 VHH 专用性有条件。
3. 最后看第 4 章：这些是网页/商业/论文模型，暂不作为本地复现主线。
4. 找论文和代码路径看附录：`report/asset_inventory.md`；找失败 PDF 原因看：`report/missing_pdfs.md`。

---

"""
(REPORT / 'nanobody_tool_survey_report.md').write_text(header + body, encoding='utf-8')
print(REPORT / 'nanobody_tool_survey_report.md')
print(REPORT / 'asset_inventory.md')
