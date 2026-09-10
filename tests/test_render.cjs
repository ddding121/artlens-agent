const assert=require('node:assert/strict');
const {blocks}=require('../artlens/static/render.js');
assert.deepEqual(blocks('### 画面观察\n- **蓝色**\n<img src=x onerror=alert(1)>'),[
 {tag:'h3',text:'画面观察'}, {tag:'li',text:'蓝色'}, {tag:'p',text:'<img src=x onerror=alert(1)>'}
]);
assert.deepEqual(blocks(''),[]);
console.log('Renderer block parsing passed (HTML remains text).');
