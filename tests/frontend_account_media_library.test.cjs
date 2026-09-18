const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','NoteAI_Pro_Demo_Framer.html'),'utf8');
function extract(name){const start=html.indexOf('function '+name+'(');assert.ok(start>=0,name);return html.slice(start,html.indexOf('\n}',start)+2);}
class Element {
  constructor(id=''){this.id=id;this.style={};this.children=[];this.innerHTML='';this.textContent='';this.disabled=false;this.accept='image/*';this.parentElement={style:{}};}
  appendChild(child){this.children.push(child);return child;}
  querySelector(){return null;}
}
function mediaFixture(status){
  const ids=['avatar-file-input','screenshotInput','inputCover','diagImgInput','genCoverInput','diagVideoInput','genVideoInput','chat-file-input'];
  const nodes=new Map(ids.map(id=>[id,new Element(id)]));
  const c=vm.createContext({_authUser:null,_publicStatus:status,PUBLIC_PRODUCT_CONTRACT:'synthetic',
    document:{getElementById:id=>{if(id==='pricing-content')return null;if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);},querySelectorAll:selector=>selector==='input[type="file"]'?ids.map(id=>nodes.get(id)):[]},
    publicImageOpen:()=> (c._publicStatus.image_open??c._publicStatus.media_open)===true,
    publicVideoOpen:()=> (c._publicStatus.video_open??c._publicStatus.media_open)===true,
    syncDiagnosisMediaType(){},nativeSyncControls(){},
  });
  vm.runInContext(extract('syncProductUI'),c);return {c,nodes,ids};
}
test('AI media closed does not disable the account avatar; AI media gates remain closed',()=>{
  const f=mediaFixture({media_open:false});f.c.syncProductUI();
  assert.equal(f.nodes.get('avatar-file-input').disabled,false);
  for(const id of ['screenshotInput','inputCover','diagImgInput','genCoverInput','diagVideoInput','genVideoInput'])assert.equal(f.nodes.get(id).disabled,true,id);
  assert.equal(f.nodes.get('chat-file-input').accept,'.txt,.md,.json,.csv');
});
test('media capability transitions retain original separate image/video gates without changing avatar state',()=>{
  const f=mediaFixture({image_open:true,video_open:false});f.c.syncProductUI();assert.equal(f.nodes.get('inputCover').disabled,false);assert.equal(f.nodes.get('diagVideoInput').disabled,true);
  f.c._publicStatus={image_open:false,video_open:true};f.c.syncProductUI();assert.equal(f.nodes.get('inputCover').disabled,true);assert.equal(f.nodes.get('diagVideoInput').disabled,false);assert.equal(f.nodes.get('avatar-file-input').disabled,false);assert.doesNotMatch(f.nodes.get('chat-file-input').accept,/image/);
});
function libraryFixture(){
  const c=vm.createContext({document:{createElement:()=>new Element(),getElementById:()=>null},_scoreColor:()=>'#777',
    escapeHtml:value=>String(value??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])),
    trackingForVersionGroup:()=>null,trackingStatusMeta:()=>({label:'未绑定',color:'#777'}),renderLibraryTrackingBadge:()=>'',renderLibraryPrimaryActions:()=>'',productActionAttributes:()=>'',openNoteDetail(){},
  });
  vm.runInContext(['librarySourceLabel','renderLibraryLifecycleStrip','buildGroupCard'].map(extract).join('\n'),c);return c;
}
for(const [source,label] of [['manual','手动保存'],['analyze','诊断原稿'],['diagnose','诊断原稿'],['generate','AI生成'],['chat','对话优化'],['future_source','来源未记录'],[undefined,'来源未记录'],['constructor','来源未记录']]){
  test('library header, origin and version consistently label '+String(source),()=>{
    const c=libraryFixture(),note={id:'synthetic',title:'合成笔记',body:'内容',domain:'美食',score:73,version:4,source,created_at:'2026-09-19'};
    const card=c.buildGroupCard({group_id:'synthetic',latest:note,versions:[note],version_count:1,score_trend:[73]});
    assert.match(card.children[0].innerHTML,new RegExp(label+' v4'));
    assert.match(c.renderLibraryLifecycleStrip({latest:note,versions:[note]}),new RegExp(label));
    assert.match(card.children[1].children[0].children[0].innerHTML,new RegExp(label+' v4'));
    if(source!=='generate')assert.doesNotMatch(card.children[0].innerHTML,/AI生成/);
  });
}
test('multiple versions retain existing header and each returned version source',()=>{
  const c=libraryFixture(),first={id:'one',source:'manual',version:1,score:70,title:'原稿',body:'甲',domain:'美食'},latest={id:'two',source:'chat',version:2,score:75,title:'优化',body:'乙',domain:'美食'};
  const card=c.buildGroupCard({group_id:'one',latest,versions:[first,latest],version_count:2,score_trend:[70,75]});
  assert.match(card.children[0].innerHTML,/最新版本 · 共2个版本/);
  const cards=card.children[1].children[0].children;assert.match(cards[0].innerHTML,/手动保存 v1/);assert.match(cards[1].innerHTML,/对话优化 v2/);
});
