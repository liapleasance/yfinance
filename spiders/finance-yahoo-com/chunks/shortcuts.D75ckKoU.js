import{o as p}from"./chartStatic.RprKAvG8.js";var i=typeof p<"u"?p:_exports.CIQ;i.Shortcuts=i.Shortcuts||function({stx:t,width:o=580,windowForEachChart:n=!0,config:r}={}){if(!t){console.warn("The Shortcuts addon requires an stx parameter");return}this.stx=t,this.width=o,this.windowForEachChart=n,this.content=this.getShortcutContent(r),this.cssRequired=!0,t.shortcuts=this,i.UI&&(this.listener=this.enableUI.bind(this),t.addObservableProperty("Layout",i.UI,this.listener),i.UI.KeystrokeHub.addHotKeyHandler("shortcuts",({stx:u,options:d})=>{u.container.ownerDocument.body.keystrokeHub.context.advertised.Layout.showShortcuts()},t));const h=this.stx.container.closest("cq-context"),c=new MutationObserver(()=>this.content=this.getShortcutContent(r));c.observe(h,{attributes:!0}),this.mo=c};i.Shortcuts.prototype.enableUI=function(){i.UI&&(i.UI.unobserveProperty("Layout",i.UI,this.listener),this.ensureMessagingAvailable(),i.UI.Layout.prototype.showShortcuts=(t,o)=>this.toggle(o,t&&t.node))};i.Shortcuts.prototype.ensureMessagingAvailable=function(){const{stx:t}=this;if(!(t&&t.uiContext&&i.UI)){setTimeout(()=>this.ensureMessagingAvailable(),1e3);return}const o=t.uiContext.topNode;Array.from(o.querySelectorAll("cq-floating-window")).find(r=>r.closest("cq-context")===o)||o.append(document.createElement("cq-floating-window"))};i.Shortcuts.prototype.getShortcutContent=function(t){const o=(t.drawingTools||[]).filter(e=>e.shortcut).map(({label:e,shortcut:s})=>`<div class="ciq-shortcut">
					<div>${e}</div>
					<div><span>Alt</span> + <span>${s.toUpperCase()}</span></div>
				</div>`).join(""),n=e=>e.charCodeAt(e.length-1)<127,r=e=>e===" + "?"<span>+</span>":e.split("+").map(s=>s&&s!==" "?"<span>"+s+"</span>":"").join(" + "),h=e=>e.map(s=>s.replace(/Arrow|Key|Digit|^ | $/g,"")).map(s=>s.replace(/\+/," + ")).reduce((s,a)=>!s.includes(a)&&n(a)?s.concat(a):s,[]).map(r).join("<br>"),c=this.stx.container.closest("cq-context");if(!c){this.mo.disconnect();return}const u=e=>c.hasAttribute(e.toLowerCase()+"-feature"),d=(t.hotkeyConfig&&t.hotkeyConfig.hotkeys||[]).map(({label:e,action:s,commands:a,extension:l})=>l&&!u(l)?"":`<div class="ciq-shortcut"><div>${e||s}</div><div>${h(a)}</div></div>`).join("");return`
		<div class="ciq-shortcut-container">
			<div>
				<div><h4>Drawing tools shortcuts</h4></div>
				<div>${o}</div>
			</div>
			<hr>
			<div>
				<div><h4>Hotkeys</h4></div>
				<div>${d}</div>
			</div>
		</div>
	`};i.Shortcuts.prototype.toggle=function(t,o){const n=o?o.closest("cq-context").CIQ.UI.context.stx:this.stx;n.dispatch("floatingWindow",{type:"shortcut",title:"Shortcuts",content:this.content,container:n.uiContext.topNode,onClose:()=>{o&&o.set&&o.set(!1)},width:this.width,status:t,tag:this.windowForEachChart?void 0:"shortcut",uiContext:n.uiContext})};
//# sourceMappingURL=shortcuts.D75ckKoU.js.map
