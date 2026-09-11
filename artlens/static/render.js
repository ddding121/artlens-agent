// 只创建文本节点与固定标签，模型输出不能注入 HTML。
(function(root){
  function blocks(text){
    return String(text).split(/\r?\n/).filter(line=>line.trim()).map(line=>{
      const heading=line.match(/^\s*#{1,6}\s+(.+)$/);
      const bullet=line.match(/^\s*[-*]\s+(.+)$/);
      return {tag:heading?'h3':bullet?'li':'p',text:(heading?.[1]||bullet?.[1]||line).replace(/\*\*([^*]+)\*\*/g,'$1')};
    });
  }
  function render(target,text,sources=[]){
    target.replaceChildren(); let list=null;
    for(const block of blocks(text)){
      const node=document.createElement(block.tag);
      for(const part of block.text.split(/(\[\d+\])/g)){
        const match=part.match(/^\[(\d+)\]$/);
        const source=match && sources.find(s=>s.source_id===Number(match[1]));
        if(source){const a=document.createElement('a');a.textContent=part;a.href='#source-'+source.source_id;a.title=source.title;node.append(a);}
        else node.append(document.createTextNode(part));
      }
      if(block.tag==='li'){
        if(!list){list=document.createElement('ul');target.append(list);}
        list.append(node);
      }else{list=null;target.append(node);}
    }
  }
  root.ArtLensText={blocks,render};
  if(typeof module!=='undefined')module.exports={blocks};
})(globalThis);
