var v=Object.defineProperty;var g=(t,s,e)=>s in t?v(t,s,{enumerable:!0,configurable:!0,writable:!0,value:e}):t[s]=e;var i=(t,s,e)=>g(t,typeof s!="symbol"?s+"":s,e);var b=64;function m(t){return t.trim().length>0}function _(t){return t.slice(0,b)}var x={status:"locked",content:null,error:null},y=class{constructor(t,s){i(this,"previewUuid");i(this,"verifyPin");i(this,"state",{...x});i(this,"listeners",new Set);this.previewUuid=t,this.verifyPin=s}getState(){return this.state}subscribe(t){return this.listeners.add(t),t(this.state),()=>{this.listeners.delete(t)}}reset(){this.setState({status:"locked",content:null,error:null})}async submitPin(t){this.setState({status:"submitting",content:null,error:null});try{const s=await this.verifyPin(this.previewUuid,t);if(s.locked){const r={status:"error",content:null,error:s.error??"Invalid PIN"};return this.setState(r),r}const e={status:"unlocked",content:s.content,error:null};return this.setState(e),e}catch{const s={status:"error",content:null,error:"Unable to verify PIN. Try again."};return this.setState(s),s}}setState(t){this.state=t;for(const s of this.listeners)s(t)}},w="320 350 1280 380",S=[{type:"path",d:"M657.2,586.4c-22.5,0-39.7-17.2-39.7-39.3s17.2-39.4,39.7-39.4,39.4,17.2,39.4,39.4-17.2,39.3-39.4,39.3ZM695,469.1c-10.3-13.4-29.4-22.5-51.6-22.5-52.3,0-91.3,46.2-91.3,100.5s38.6,100.5,91.3,100.5,41.2-8.8,51.6-22.9v18h65.3v-191.4h-65.3v18Z"},{type:"path",d:"M900.6,446.6c-21.8,0-38.6,8.4-50.4,23.3v-103.5h-67.2v276.2h67.6v-102c0-19.9,9.6-31.7,24.8-31.7s23.3,10.3,23.3,29.4v104.3h67.6v-120.3c0-46.6-25.2-75.6-65.7-75.6Z"},{type:"path",d:"M1299.1,585.7c-22.2,0-38.2-17.2-38.2-38.6s16-38.6,38.2-38.6,38.2,17.2,38.2,38.6-16.1,38.6-38.2,38.6ZM1299.1,446.6c-58.4,0-102.4,43.2-102.4,100.5s43.9,100.5,102.4,100.5,102.4-43.2,102.4-100.5-43.9-100.5-102.4-100.5Z"},{type:"path",d:"M1082.8,585.7c-22.2,0-38.2-17.2-38.2-38.6s16-38.6,38.2-38.6,38.2,17.2,38.2,38.6c0,21.4-16.1,38.6-38.2,38.6ZM1082.8,446.6c-58.4,0-102.4,43.2-102.4,100.5s43.9,100.5,102.4,100.5,102.4-43.2,102.4-100.5c0-57.3-43.9-100.5-102.4-100.5Z"},{type:"polygon",points:"495.2 451.2 450.9 563.5 407 451.2 333.6 451.2 415.4 644.1 386 713.6 457.8 713.6 566.7 451.2 495.2 451.2"},{type:"path",d:"M1455.3,556.6c-26,0-45.5,21-45.5,45.5s18.7,43.9,44,43.9,45.5-20.6,45.5-45.5-18.7-43.9-43.9-43.9Z"},{type:"polygon",points:"1506.1 366.4 1434.3 539.8 1514.6 539.8 1586.4 366.4 1506.1 366.4"}],k=S.map(t=>t.type==="path"?`<path d="${t.d}"/>`:`<polygon points="${t.points}"/>`).join("");function P(){return`<svg class="lsp-prompt__logo" xmlns="http://www.w3.org/2000/svg" viewBox="${w}" role="img" aria-label="Yahoo" focusable="false">${k}</svg>`}var E=`
  <div class="lsp-prompt" part="prompt">
    <div class="lsp-prompt__card" part="card">
      <div class="lsp-prompt__brand">${P()}</div>
      <h1 class="lsp-prompt__title">Enter your PIN</h1>
      <p class="lsp-prompt__description">
        This preview is PIN-protected.
      </p>
      <form class="lsp-prompt__form" part="form">
        <input
          id="lsp-pin"
          class="lsp-prompt__input"
          name="pin"
          type="password"
          autocomplete="one-time-code"
          maxlength="${b}"
          aria-label="PIN"
          part="input"
        />
        <p class="lsp-prompt__error" part="error" hidden role="alert"></p>
        <button type="submit" class="lsp-prompt__submit" part="submit" disabled>
          View preview
        </button>
      </form>
    </div>
    <p class="lsp-prompt__footer">
      Previews are private and expire. Do not share this link publicly.
    </p>
  </div>
  <div class="lsp-unlocked" part="unlocked" hidden>
    <div class="lsp-unlocked__banner" role="status">
      Secure preview — do not distribute
    </div>
    <div class="lsp-unlocked__slot" part="content"></div>
  </div>
`,l,M=(l=class extends HTMLElement{constructor(){super(...arguments);i(this,"_verifyPin",null);i(this,"renderUnlocked",null);i(this,"session",null);i(this,"unsubscribe",null);i(this,"root",null)}static register(e=l.tagName){typeof customElements>"u"||customElements.get(e)||customElements.define(e,l)}static get observedAttributes(){return["preview-uuid"]}get verifyPin(){return this._verifyPin}set verifyPin(e){this._verifyPin=e,this.ensureSession()}connectedCallback(){if(!this.root){this.root=this.attachShadow({mode:"open"});const e=document.createElement("style");e.textContent=A,this.root.append(e);const r=document.createElement("div");r.innerHTML=E,this.root.append(r),this.bindForm()}this.ensureSession()}disconnectedCallback(){this.unsubscribe&&(this.unsubscribe(),this.unsubscribe=null)}attributeChangedCallback(e){e==="preview-uuid"&&this.ensureSession()}get previewUuid(){return this.getAttribute("preview-uuid")??""}set previewUuid(e){this.setAttribute("preview-uuid",e)}ensureSession(){!this.previewUuid||!this.verifyPin||(this.unsubscribe&&(this.unsubscribe(),this.unsubscribe=null),this.session=new y(this.previewUuid,this.verifyPin),this.unsubscribe=this.session.subscribe(e=>this.applyState(e)))}bindForm(){var n,a,p;const e=(n=this.root)==null?void 0:n.querySelector("form"),r=(a=this.root)==null?void 0:a.querySelector("input"),o=(p=this.root)==null?void 0:p.querySelector("button");!e||!r||!o||(r.addEventListener("input",()=>{r.value=_(r.value),o.disabled=!m(r.value)}),e.addEventListener("submit",async c=>{if(c.preventDefault(),!this.verifyPin){this.showError("verifyPin is not configured");return}const d=r.value;m(d)&&(this.ensureSession(),this.session&&(r.value="",o.disabled=!0,await this.session.submitPin(d)))}))}applyState(e){var c,d,u,f,h;const r=(c=this.root)==null?void 0:c.querySelector(".lsp-prompt"),o=(d=this.root)==null?void 0:d.querySelector(".lsp-unlocked"),n=(u=this.root)==null?void 0:u.querySelector(".lsp-prompt__error"),a=(f=this.root)==null?void 0:f.querySelector("button"),p=(h=this.root)==null?void 0:h.querySelector(".lsp-unlocked__slot");if(e.status==="unlocked"&&e.content){r==null||r.setAttribute("hidden",""),o==null||o.removeAttribute("hidden"),p instanceof HTMLElement&&(p.replaceChildren(),this.renderUnlocked&&this.renderUnlocked(e.content,p)),this.dispatchEvent(new CustomEvent("lsp:unlocked",{detail:{previewUuid:this.previewUuid,content:e.content},bubbles:!0,composed:!0}));return}o==null||o.setAttribute("hidden",""),r==null||r.removeAttribute("hidden"),a&&(a.textContent=e.status==="submitting"?"Verifying…":"View preview"),n instanceof HTMLElement&&(e.error?(n.hidden=!1,n.textContent=e.error):(n.hidden=!0,n.textContent=""))}showError(e){var o;const r=(o=this.root)==null?void 0:o.querySelector(".lsp-prompt__error");r instanceof HTMLElement&&(r.hidden=!1,r.textContent=e)}},i(l,"tagName","lightyear-secure-preview"),l),A=`
  :host {
    display: block;
    font-family: "Yahoo Sans", "Helvetica Neue", Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    --lsp-brand: #7d2eff;
    --lsp-brand-hover: #6a1fe0;
    --lsp-brand-active: #5a14c7;
    --lsp-brand-focus: color-mix(in srgb, #7d2eff 35%, transparent);
  }
  .lsp-prompt {
    --lsp-bg: #f0f3f5;
    --lsp-card: #ffffff;
    --lsp-border: #d4dae0;
    --lsp-border-strong: #b8c0c8;
    --lsp-input-bg: #f7f9fa;
    --lsp-input-border: #c5ccd3;
    --lsp-text: #1b2028;
    --lsp-muted: #5c6670;
    --lsp-text-inverse: #ffffff;
    --lsp-danger: #c9372c;
    --lsp-logo: var(--lsp-brand);
    --lsp-shadow: 0 1px 2px rgba(27, 32, 40, 0.06), 0 8px 24px rgba(27, 32, 40, 0.08);
    box-sizing: border-box;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1.5rem;
    padding: 2rem 1.25rem;
    background: var(--lsp-bg);
    color: var(--lsp-text);
    color-scheme: light dark;
  }
  @media (prefers-color-scheme: dark) {
    .lsp-prompt {
      --lsp-bg: #0f1115;
      --lsp-card: #1b2028;
      --lsp-border: #3a4149;
      --lsp-border-strong: #525a63;
      --lsp-input-bg: #14181f;
      --lsp-input-border: #3a4149;
      --lsp-text: #f0f3f5;
      --lsp-muted: #9aa3ad;
      --lsp-danger: #f07178;
      --lsp-logo: #ffffff;
      --lsp-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), 0 12px 32px rgba(0, 0, 0, 0.45);
    }
  }
  :host-context(html.uds-color-mode-light) .lsp-prompt,
  :host-context(.uds-color-mode-light) .lsp-prompt {
    --lsp-bg: #f0f3f5;
    --lsp-card: #ffffff;
    --lsp-border: #d4dae0;
    --lsp-border-strong: #b8c0c8;
    --lsp-input-bg: #f7f9fa;
    --lsp-input-border: #c5ccd3;
    --lsp-text: #1b2028;
    --lsp-muted: #5c6670;
    --lsp-danger: #c9372c;
    --lsp-logo: var(--lsp-brand);
    --lsp-shadow: 0 1px 2px rgba(27, 32, 40, 0.06), 0 8px 24px rgba(27, 32, 40, 0.08);
  }
  :host-context(html.uds-color-mode-dark) .lsp-prompt,
  :host-context(.uds-color-mode-dark) .lsp-prompt {
    --lsp-bg: #0f1115;
    --lsp-card: #1b2028;
    --lsp-border: #3a4149;
    --lsp-border-strong: #525a63;
    --lsp-input-bg: #14181f;
    --lsp-input-border: #3a4149;
    --lsp-text: #f0f3f5;
    --lsp-muted: #9aa3ad;
    --lsp-danger: #f07178;
    --lsp-logo: #ffffff;
    --lsp-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), 0 12px 32px rgba(0, 0, 0, 0.45);
  }
  .lsp-prompt__card {
    box-sizing: border-box;
    width: min(100%, 24rem);
    padding: 2rem 1.75rem 1.75rem;
    border: 1px solid var(--lsp-border);
    border-radius: 12px;
    background: var(--lsp-card);
    box-shadow: var(--lsp-shadow);
    text-align: center;
  }
  .lsp-prompt__brand {
    margin: 0 0 1.25rem;
    line-height: 0;
    display: flex;
    justify-content: center;
  }
  .lsp-prompt__logo {
    display: block;
    flex-shrink: 0;
    width: 7.25rem;
    height: auto;
    overflow: visible;
    color: var(--lsp-logo);
  }
  .lsp-prompt__logo path,
  .lsp-prompt__logo polygon { fill: currentColor; }
  .lsp-prompt__eyebrow {
    margin: 0 0 0.5rem;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--lsp-muted);
  }
  .lsp-prompt__title {
    margin: 0 0 0.5rem;
    font-size: 1.375rem;
    font-weight: 700;
    color: var(--lsp-text);
  }
  .lsp-prompt__description {
    margin: 0 0 1.5rem;
    color: var(--lsp-muted);
    line-height: 1.5;
    font-size: 0.9375rem;
  }
  .lsp-prompt__form { display: flex; flex-direction: column; gap: 0.5rem; }
  .lsp-prompt__label { font-size: 0.8125rem; font-weight: 600; color: var(--lsp-text); }
  .lsp-prompt__input {
    box-sizing: border-box;
    width: 100%;
    height: 52px;
    padding: 0 1rem;
    border: 1px solid var(--lsp-input-border);
    border-radius: 8px;
    background: var(--lsp-input-bg);
    color: var(--lsp-text);
    font-size: 1.25rem;
    font-weight: 600;
    letter-spacing: 0.4em;
    text-align: center;
  }
  .lsp-prompt__input:focus {
    outline: none;
    border-color: var(--lsp-brand);
    background: var(--lsp-card);
    box-shadow: 0 0 0 3px var(--lsp-brand-focus);
  }
  .lsp-prompt__error { color: var(--lsp-danger); margin: 0.15rem 0 0; font-size: 0.8125rem; }
  .lsp-prompt__submit {
    margin-top: 0.75rem;
    width: 100%;
    height: 40px;
    border: 0;
    border-radius: 8px;
    background: var(--lsp-brand);
    color: var(--lsp-text-inverse);
    font-size: 0.9375rem;
    font-weight: 650;
    cursor: pointer;
  }
  .lsp-prompt__submit:disabled { opacity: 0.4; cursor: not-allowed; }
  .lsp-prompt__footer {
    margin: 0;
    max-width: 24rem;
    font-size: 0.75rem;
    line-height: 1.4;
    color: var(--lsp-muted);
    text-align: center;
  }
  .lsp-unlocked__banner {
    padding: 0.65rem 1rem;
    background: var(--lsp-brand);
    color: #fff;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-align: center;
    text-transform: uppercase;
  }
  [hidden] { display: none !important; }
`;export{M as LightyearSecurePreviewElement};
//# sourceMappingURL=element.BIVwhLDE.js.map
