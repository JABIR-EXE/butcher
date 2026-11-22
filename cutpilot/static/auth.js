(() => {
  const params = new URLSearchParams(location.search);
  const plan = params.get('plan');
  const planSelect = document.querySelector('#signup-plan');
  if (planSelect && ['starter','professional','multi-location'].includes(plan)) planSelect.value = plan;
  const show = (node, message, type='error') => { if(!node) return; node.textContent = message; node.className = `auth-message show ${type}`; };
  const formMessage = document.querySelector('#form-message');
  const modeMessage = document.querySelector('#mode-message');
  const config = fetch('/api/config').then(r=>r.json()).catch(()=>({mode:'unavailable'}));
  config.then(c=>{
    if (modeMessage && c.mode !== 'saas') show(modeMessage, 'This preview is running locally. Account registration and sign-in work only after hosted SaaS mode is configured.', 'error');
  });
  async function submitForm(form, endpoint, onSuccess) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      const data = Object.fromEntries(new FormData(form).entries());
      if (endpoint === '/api/auth/reset-password') data.token = params.get('token') || '';
      btn.disabled = true; const old = btn.textContent; btn.textContent = 'Please wait…';
      try {
        const response = await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Request could not be completed.');
        onSuccess ? onSuccess(result) : show(formMessage, result.message || 'Done.', 'success');
      } catch (error) { show(formMessage, error.message || 'Something went wrong.'); }
      finally { btn.disabled = false; btn.textContent = old; }
    });
  }
  const login = document.querySelector('#login-form');
  if (login) submitForm(login,'/api/auth/login',()=>location.href='/app');
  const signup = document.querySelector('#signup-form');
  if (signup) submitForm(signup,'/api/auth/register',result=>{
    if (result.verification_required) show(formMessage, result.message, 'success');
    else location.href='/app';
  });
  const forgot = document.querySelector('#forgot-form');
  if (forgot) submitForm(forgot,'/api/auth/forgot-password');
  const reset = document.querySelector('#reset-form');
  if (reset) submitForm(reset,'/api/auth/reset-password',result=>{show(formMessage,result.message,'success');setTimeout(()=>location.href='/login',1800);});
})();
