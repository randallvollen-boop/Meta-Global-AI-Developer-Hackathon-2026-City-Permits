# Netlify front door

This static page gives the Render service time to wake before sending a visitor to the ACME City Permits demo.

## How readiness checking works

The browser requests `/demo-ready` on the same Netlify origin. The rewrite in `netlify.toml` proxies that request to `https://acme-city-permits.onrender.com/readyz`. This preserves an observable HTTP response without a cross-origin browser request. A `no-cors` fetch was not used because its opaque response does not expose the status, and an image probe was not used because `/readyz` returns JSON rather than image data.

The page checks every three seconds, redirects after a readiness response whose JSON status is `ready`, and stops automatic checks after three minutes. The direct demo link remains visible throughout.

## Deploy for Randall

1. Sign in to Netlify and open the site for `acme-city-permits.netlify.app`.
2. Set the repository to the private ACME City Permits repository.
3. Set the production branch to the branch that contains this folder after Randall has approved and merged it.
4. Set the base directory to `netlify`.
5. Leave the publish directory as `.`. The value is also pinned in `netlify.toml`.
6. Leave the build command empty because the page is static.
7. Review the deploy preview at 390px and on a desktop in both light and dark appearance settings.
8. Confirm `/demo-ready` proxies the Render readiness endpoint and that a successful check redirects to the live demo.
9. Publish the production deploy only after Randall approves it.

No secrets, environment variables, packages, or external browser scripts are required.
