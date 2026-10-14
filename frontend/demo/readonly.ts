const mutations = /^(?:add (?!.*by hand)|edit|delete|merge|move|split|remove|save|accept|dismiss|ignore|not travel|ask ai|ask again|ask about|connect|reconnect|disconnect|sign |import|restore|download (?:a |the )?backup|set up offline|turn |enable|disable|refresh|mark |finish|unfinish|trust|clear|done|claim|create|scan|look back|stop ignoring|apply|match |attach|use this|export|download)/i;
const allowedInputs = (element: Element): boolean => (!element.closest('form[data-editor]') && /^(?:#stats|#trips)/.test(location.hash)) || !!element.closest('[aria-label="Route replay"], [aria-label="Travel map"], [aria-label="Stats filters"]') || element.getAttribute('type') === 'search' || element.getAttribute('placeholder')?.toLowerCase().includes('search') === true;
function restricted(element: HTMLElement): boolean {
  if (element instanceof HTMLAnchorElement) return !!element.getAttribute('href') && !element.getAttribute('href')!.startsWith('#');
  if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) return !allowedInputs(element);
  const label = element.getAttribute('aria-label') || element.textContent?.trim() || '';
  const settings = location.hash.startsWith('#settings/');
  return mutations.test(label) || /^(?:It’s a new booking|This is me)/i.test(label) || !!element.closest('[data-testid="match-item"], [data-testid="who-item"]') || element.getAttribute('type') === 'submit' || (settings && !/^(?:back|close|cancel|show|hide|view|copy|open|read)/i.test(label));
}
export function protectDemo(): void {
  const apply = () => document.querySelectorAll<HTMLElement>('button,a[href],input,textarea,select,[role="menuitem"],[role="switch"]').forEach(element=>{
    if (!restricted(element) && !element.dataset.demoDisabled) return;
    element.dataset.demoDisabled = 'true';
    element.setAttribute('aria-disabled','true');
    element.title = 'Unavailable in the read-only demo';
    if ('disabled' in element && !(element as HTMLButtonElement).disabled) (element as HTMLButtonElement).disabled = true;
    if (element instanceof HTMLAnchorElement) element.removeAttribute('href');
  });
  new MutationObserver(apply).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['href','disabled','aria-label']});
  window.addEventListener('hashchange',apply);
  document.addEventListener('click',event=>{
    const element = (event.target as Element | null)?.closest<HTMLElement>('button,a,[role="menuitem"],[role="switch"]');
    if (!element || (!restricted(element) && !element.dataset.demoDisabled)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  },true);
  document.addEventListener('keydown',event=>{
    const element = (event.target as Element | null)?.closest<HTMLElement>('[data-demo-disabled]');
    if (!element || !['Enter',' '].includes(event.key)) return;
    event.preventDefault();event.stopImmediatePropagation();
  },true);
  document.addEventListener('submit',event=>{event.preventDefault();event.stopImmediatePropagation();},true);
  apply();
}
