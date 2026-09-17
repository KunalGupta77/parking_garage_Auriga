function showError(message) {
  const el = document.getElementById("error-message");
  el.textContent = message;
  el.classList.remove("hidden");
}

async function postJson(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  return { ok: resp.ok, status: resp.status, data };
}

const registerForm = document.getElementById("register-form");
if (registerForm) {
  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("name").value.trim();
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    const { ok, data } = await postJson("/api/register", { name, email, password });
    if (!ok) {
      showError(data.error || "Registration failed");
      return;
    }
    window.location.href = "/login";
  });
}

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    const { ok, data } = await postJson("/api/login", { email, password });
    if (!ok) {
      showError(data.error || "Login failed");
      return;
    }
    window.location.href = "/dashboard";
  });
}
