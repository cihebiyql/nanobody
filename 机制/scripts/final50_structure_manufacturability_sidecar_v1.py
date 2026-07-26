#!/usr/bin/env python3
"""Final50 structure-derived manufacturability sidecar.

Computes descriptive, pose-aggregated surface/terminal/PTM metrics from existing
VHH-PVRIG docking PDBs. It neither predicts CHO yield/purity nor changes the
mechanism rank. Uses an in-script Shrake-Rupley SASA implementation to keep the
production run dependency-free.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, re, statistics, sys
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

AA3 = {"ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V","SEC":"U","PYL":"O"}
RADII = {"H":1.20,"C":1.70,"N":1.55,"O":1.52,"S":1.80,"P":1.80,"SE":1.90}
HYDRO = set("AILMFWVY")
POS = set("KRH")
NEG = set("DE")
PROBE = 1.4
# Runtime-quality compromise: 60 uniformly distributed points per atom.
SPHERE_N = 60
SPHERE = []
phi = math.pi * (3.0 - math.sqrt(5.0))
for i in range(SPHERE_N):
    y = 1 - (i / float(SPHERE_N - 1)) * 2
    r = math.sqrt(max(0.0, 1 - y*y))
    theta = phi * i
    SPHERE.append((math.cos(theta)*r, y, math.sin(theta)*r))

@dataclass(frozen=True)
class Atom:
    chain: str
    reskey: tuple
    resname: str
    name: str
    element: str
    x: float
    y: float
    z: float


def parse_pdb(path: Path):
    atoms=[]; residues={}; order=[]
    with path.open(errors="replace") as f:
        for line in f:
            if not line.startswith(("ATOM  ","HETATM")): continue
            alt=line[16:17]
            if alt not in (" ","A","1"): continue
            resname=line[17:20].strip().upper()
            if resname not in AA3: continue
            chain=line[21:22] or "_"
            try:
                resseq=int(line[22:26]); icode=line[26:27].strip()
                x=float(line[30:38]); y=float(line[38:46]); z=float(line[46:54])
            except ValueError: continue
            name=line[12:16].strip(); elem=line[76:78].strip().upper() or re.sub('[^A-Za-z]','',name)[:1].upper()
            if elem == "D": elem="H"
            if elem not in RADII: elem="C"
            key=(chain,resseq,icode)
            if key not in residues:
                residues[key]={"aa":AA3[resname],"atoms":[],"order":len(order)}; order.append(key)
            a=Atom(chain,key,resname,name,elem,x,y,z); atoms.append(a); residues[key]["atoms"].append(a)
    return atoms,residues,order


def chain_sequences(residues, order):
    d=defaultdict(list); keys=defaultdict(list)
    for key in order:
        d[key[0]].append(residues[key]["aa"]); keys[key[0]].append(key)
    return {c:"".join(v) for c,v in d.items()},keys


def best_chain(target, seqs):
    # Substring match normally gives identity 1; fallback longest common sequence ratio.
    choices=[]
    for c,s in seqs.items():
        if s == target: score=1.0
        elif s and (s in target or target in s): score=min(len(s),len(target))/max(len(s),len(target))
        else:
            # Lightweight LCS ratio to tolerate isolated unresolved PDB residues.
            prev=[0]*(len(target)+1)
            for a in s:
                cur=[0]
                for j,b in enumerate(target,1): cur.append(prev[j-1]+1 if a==b else max(prev[j],cur[-1]))
                prev=cur
            score=prev[-1]/max(len(target),1)
        choices.append((score,c,s))
    score,c,s=max(choices)
    if score < 0.90: raise ValueError(f"No reliable VHH chain (best={c}, identity_proxy={score:.3f})")
    return c,s,score


def global_map(target, observed, obs_keys):
    # Needleman-Wunsch mapping target 0-based index -> PDB residue key.
    n,m=len(target),len(observed); gap=-2
    dp=[[0]*(m+1) for _ in range(n+1)]
    bt=[[None]*(m+1) for _ in range(n+1)]
    for i in range(1,n+1): dp[i][0]=i*gap; bt[i][0]='U'
    for j in range(1,m+1): dp[0][j]=j*gap; bt[0][j]='L'
    for i in range(1,n+1):
        for j in range(1,m+1):
            opts=[(dp[i-1][j-1]+(2 if target[i-1]==observed[j-1] else -1),'D'),(dp[i-1][j]+gap,'U'),(dp[i][j-1]+gap,'L')]
            dp[i][j],bt[i][j]=max(opts,key=lambda x:x[0])
    mapping={}; i=n; j=m
    while i or j:
        b=bt[i][j]
        if b=='D':
            if target[i-1]==observed[j-1]: mapping[i-1]=obs_keys[j-1]
            i-=1; j-=1
        elif b=='U': i-=1
        else: j-=1
    return mapping


def grid(atoms, cell=4.0):
    g=defaultdict(list)
    for a in atoms: g[(int(math.floor(a.x/cell)),int(math.floor(a.y/cell)),int(math.floor(a.z/cell)))].append(a)
    return g,cell


def nearby(g, cell, x,y,z, radius):
    qx,qy,qz=(int(math.floor(x/cell)),int(math.floor(y/cell)),int(math.floor(z/cell))); n=math.ceil(radius/cell)
    for i in range(qx-n,qx+n+1):
        for j in range(qy-n,qy+n+1):
            for k in range(qz-n,qz+n+1):
                yield from g.get((i,j,k),())


def sasa(query_atoms, occluders):
    # Per-residue Shrake-Rupley SASA; query atoms always occlude each other.
    all_occ=occluders
    g,cell=grid(all_occ)
    out=defaultdict(float)
    for a in query_atoms:
        r=RADII[a.element]+PROBE; unit_area=4*math.pi*r*r/SPHERE_N
        for sx,sy,sz in SPHERE:
            x,y,z=a.x+r*sx,a.y+r*sy,a.z+r*sz
            blocked=False
            for b in nearby(g,cell,x,y,z,4.0):
                if b is a: continue
                rb=RADII[b.element]+PROBE
                dx=x-b.x; dy=y-b.y; dz=z-b.z
                if dx*dx+dy*dy+dz*dz < rb*rb:
                    blocked=True; break
            if not blocked: out[a.reskey]+=unit_area
    return out


def center(atoms):
    if not atoms: return (0.,0.,0.)
    return tuple(sum(getattr(a,k) for a in atoms)/len(atoms) for k in ('x','y','z'))

def dist(a,b): return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))

def residue_contacts(res_atoms, target_atoms, cutoff=4.5):
    g,cell=grid(target_atoms)
    for a in res_atoms:
        for b in nearby(g,cell,a.x,a.y,a.z,cutoff):
            if (a.x-b.x)**2+(a.y-b.y)**2+(a.z-b.z)**2 <= cutoff*cutoff: return True
    return False

def min_distance(res_atoms,target_atoms):
    g,cell=grid(target_atoms); best=float('inf')
    for a in res_atoms:
        for b in nearby(g,cell,a.x,a.y,a.z,40):
            d=((a.x-b.x)**2+(a.y-b.y)**2+(a.z-b.z)**2)**0.5
            if d<best: best=d
    return best if best<float('inf') else None

def patch_stats(keys,residues,free_sasa,aa_set,cutoff):
    active=[k for k in keys if residues[k]['aa'] in aa_set and free_sasa.get(k,0)>=15.0]
    if not active: return (0,0.0)
    ctr={k:center(residues[k]['atoms']) for k in active}; unseen=set(active); largest=(0,0.0)
    while unseen:
        seed=unseen.pop(); q=[seed]; comp=[seed]
        while q:
            u=q.pop(); close=[v for v in list(unseen) if dist(ctr[u],ctr[v])<=cutoff]
            for v in close: unseen.remove(v); q.append(v); comp.append(v)
        cand=(len(comp),sum(free_sasa.get(k,0) for k in comp))
        if cand > largest: largest=cand
    return largest

def motif_hits(seq,cdrs):
    # motif rows reference each constituent residue. Motifs are review flags only.
    hits=[]
    cdr_ranges=[]
    for name,cdr in (('CDR1',cdrs.get('cdr1','')),('CDR2',cdrs.get('cdr2','')),('CDR3',cdrs.get('cdr3',''))):
        if not cdr: continue
        start=seq.find(cdr)
        if start>=0: cdr_ranges.append((name,start,start+len(cdr)))
    def region(i):
        for n,s,e in cdr_ranges:
            if s<=i<e:return n
        return 'FRAMEWORK'
    patterns=[('DEAMIDATION','N[GST]'),('ISOMERIZATION','D[DGST]'),('ACID_CLIPPING','DP'),('OXIDATION_RESIDUE','[MW]')]
    for typ,pat in patterns:
        for m in re.finditer(pat,seq):
            for i in range(m.start(),m.end()): hits.append({'motif_type':typ,'motif':m.group(),'seq_index_1based':i+1,'region':region(i)})
    # Deduplicate residues that participate in same motif type/position.
    seen=set(); ans=[]
    for h in hits:
        key=(h['motif_type'],h['seq_index_1based'])
        if key not in seen: seen.add(key); ans.append(h)
    return ans

def num(x): return '' if x is None else f'{x:.6f}'

def process(job):
    candidate, row, pdb_path = job['candidate'], job['row'], Path(job['pdb_path'])
    atoms,residues,order=parse_pdb(pdb_path); seqs,chains=chain_sequences(residues,order)
    vhh_chain,observed,identity=best_chain(row['sequence'],seqs)
    vkeys=chains[vhh_chain]; mapping=global_map(row['sequence'],observed,vkeys)
    vatoms=[a for a in atoms if a.chain==vhh_chain]; target=[a for a in atoms if a.chain!=vhh_chain]
    free=sasa(vatoms,vatoms); bound=sasa(vatoms,atoms)
    h_n,h_area=patch_stats(vkeys,residues,free,HYDRO,8.0)
    p_n,p_area=patch_stats(vkeys,residues,free,POS,10.0)
    n_n,n_area=patch_stats(vkeys,residues,free,NEG,10.0)
    ckey=mapping.get(len(row['sequence'])-1)
    c_atoms=residues[ckey]['atoms'] if ckey else []
    c_min=min_distance(c_atoms,target) if c_atoms else None
    pose={
      'candidate_id':candidate,'final_rank':row.get('final_rank',''),'top10_rank':row.get('top10_rank',''),'pdb_path':str(pdb_path),
      'vhh_chain':vhh_chain,'chain_identity_proxy':num(identity),'mapped_sequence_fraction':num(len(mapping)/len(row['sequence'])),
      'free_vhh_sasa_a2':num(sum(free.values())),'bound_vhh_sasa_a2':num(sum(bound.values())),
      'binding_buried_sasa_a2':num(sum(free.values())-sum(bound.values())),
      'largest_hydrophobic_patch_residues':h_n,'largest_hydrophobic_patch_free_sasa_a2':num(h_area),
      'largest_positive_patch_residues':p_n,'largest_positive_patch_free_sasa_a2':num(p_area),
      'largest_negative_patch_residues':n_n,'largest_negative_patch_free_sasa_a2':num(n_area),
      'c_terminal_target_min_distance_a':num(c_min),'c_terminal_target_contact_4p5a':str(bool(c_min is not None and c_min<=4.5)),
    }
    motifs=[]
    for h in motif_hits(row['sequence'],{'cdr1':row.get('cdr1',''),'cdr2':row.get('cdr2',''),'cdr3':row.get('cdr3','')}):
        idx=h['seq_index_1based']-1; key=mapping.get(idx); ra=residues[key]['atoms'] if key else []
        fs=free.get(key,0.0) if key else None; bs=bound.get(key,0.0) if key else None
        contact=residue_contacts(ra,target) if ra else None
        motifs.append({**pose,**h,'pdb_residue':f'{key[0]}:{key[1]}{key[2]}' if key else '',
          'free_residue_sasa_a2':num(fs),'bound_residue_sasa_a2':num(bs),
          'bound_to_free_sasa_fraction':num((bs/fs) if fs and fs>0 else None),'pvrig_contact_4p5a':str(contact) if contact is not None else ''})
    return pose,motifs

def median(vals):
    vals=[float(v) for v in vals if v not in ('',None)]
    return statistics.median(vals) if vals else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--final50-tsv',required=True); ap.add_argument('--manifest-tsv',required=True); ap.add_argument('--outdir',required=True); ap.add_argument('--workers',type=int,default=16); ap.add_argument('--limit-candidates',type=int,default=0)
    a=ap.parse_args(); out=Path(a.outdir); out.mkdir(parents=True,exist_ok=False)
    rows={r['candidate_id']:r for r in csv.DictReader(open(a.final50_tsv),delimiter='\t')}
    manifest=list(csv.DictReader(open(a.manifest_tsv),delimiter='\t'))
    jobs=[{'candidate':m['candidate_id'],'row':rows[m['candidate_id']],'pdb_path':m['pdb_path']} for m in manifest if m['candidate_id'] in rows]
    if a.limit_candidates:
        keep=set(sorted(rows,key=lambda x:int(rows[x]['final_rank']))[:a.limit_candidates]); jobs=[j for j in jobs if j['candidate'] in keep]; rows={k:v for k,v in rows.items() if k in keep}
    expected=len(rows)*8
    if len(jobs)!=expected: raise SystemExit(f'Expected {expected} structures, got {len(jobs)}')
    poses=[]; motifs=[]; errors=[]
    with ProcessPoolExecutor(max_workers=min(a.workers,32)) as ex:
        futs={ex.submit(process,j):j for j in jobs}
        for f in as_completed(futs):
            j=futs[f]
            try:
                p,m=f.result(); poses.append(p); motifs.extend(m)
            except Exception as e: errors.append({'candidate_id':j['candidate'],'pdb_path':j['pdb_path'],'error':repr(e)})
    if errors:
        with (out/'errors.tsv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=errors[0]);w.writeheader();w.writerows(errors)
        raise SystemExit(f'{len(errors)} pose failures; see errors.tsv')
    poses.sort(key=lambda x:(int(x['final_rank']),x['pdb_path'])); motifs.sort(key=lambda x:(int(x['final_rank']),x['seq_index_1based'],x['pdb_path']))
    def write(name,data):
        keys=list(data[0]) if data else []
        with (out/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=keys,delimiter='\t');w.writeheader();w.writerows(data)
    write('pose_surface_metrics.tsv',poses); write('ptm_exposure_metrics.tsv',motifs)
    agg=[]
    for cid,row in sorted(rows.items(),key=lambda x:int(x[1]['final_rank'])):
        pp=[p for p in poses if p['candidate_id']==cid]; mm=[m for m in motifs if m['candidate_id']==cid]
        def med(k): return median([p[k] for p in pp])
        c_contact=sum(p['c_terminal_target_contact_4p5a']=='True' for p in pp)
        exposed=[m for m in mm if float(m['free_residue_sasa_a2'] or 0)>=20 and float(m['bound_to_free_sasa_fraction'] or 0)>=0.5]
        exposed_noncontact=[m for m in exposed if m['pvrig_contact_4p5a']=='False']
        acid=[m for m in exposed_noncontact if m['motif_type']=='ACID_CLIPPING']
        iso=[m for m in exposed_noncontact if m['motif_type']=='ISOMERIZATION']
        tier='REVIEW' if acid or len(iso)>=2 or c_contact else 'NO_HIGH_STRUCTURAL_FLAG'
        agg.append({'candidate_id':cid,'final_rank':row.get('final_rank',''),'top10_rank':row.get('top10_rank',''),'pose_count':len(pp),
         'median_free_vhh_sasa_a2':num(med('free_vhh_sasa_a2')),'median_binding_buried_sasa_a2':num(med('binding_buried_sasa_a2')),
         'median_largest_hydrophobic_patch_residues':num(med('largest_hydrophobic_patch_residues')),'median_largest_hydrophobic_patch_free_sasa_a2':num(med('largest_hydrophobic_patch_free_sasa_a2')),
         'median_largest_positive_patch_residues':num(med('largest_positive_patch_residues')),'median_largest_negative_patch_residues':num(med('largest_negative_patch_residues')),
         'minimum_c_terminal_target_distance_a':num(min(float(p['c_terminal_target_min_distance_a']) for p in pp if p['c_terminal_target_min_distance_a']!='')),
         'c_terminal_contact_pose_count':c_contact,'ptm_motif_rows':len(mm),'exposed_ptm_residue_rows':len(exposed),'exposed_noncontact_ptm_rows':len(exposed_noncontact),
         'exposed_noncontact_acid_clipping_rows':len(acid),'exposed_noncontact_isomerization_rows':len(iso),'structural_ptm_review_status':tier,
         'claim_boundary':'descriptive structural sidecar; not CHO yield/purity, BLI, Kd, IC50, aggregation, or experimental blocking'})
    write('candidate_structure_manufacturability_sidecar.tsv',agg)
    receipt={'schema_version':'pvrig.final50.structure_manufacturability_sidecar.v1','state':'COMPLETE','candidates':len(rows),'pose_models':len(poses),'ptm_rows':len(motifs),'workers':min(a.workers,32),'sasa_method':'in-script Shrake-Rupley, 60 sphere points/atom, probe 1.4A','claim_boundary':'Descriptive computational structural sidecar only; it does not predict experimental CHO yield, purity, aggregation, BLI, Kd, IC50, or blocking.',
      'input_sha256':{str(Path(a.final50_tsv)):hashlib.sha256(Path(a.final50_tsv).read_bytes()).hexdigest(),str(Path(a.manifest_tsv)):hashlib.sha256(Path(a.manifest_tsv).read_bytes()).hexdigest()}}
    (out/'STRUCTURE_SIDECAR_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
if __name__=='__main__': main()
