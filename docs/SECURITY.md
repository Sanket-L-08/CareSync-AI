# Security notes and remaining work

## Verified in this release
Automated tests (`services/api/tests`, 18 passing) cover: authentication required, password policy, clinician self-signup
blocked, cross-patient isolation, caregiver grants and revocation, family read-only scope, consent withdrawal revoking
access, admin denied clinical data without break-glass, unverified clinicians blocked, signed-note immutability, alert
generation, allergy warnings, double-booking prevention, encryption of stored files, file-type sniffing, account lockout,
refresh-token reuse detection, audit-chain integrity, security headers, and production config fail-closed.

## Known limitations — action before going live
1. **Next.js 14 is past end-of-life.** 14.2.35 (latest 14.x) still has published advisories. This app renders only on
   the client — no image optimizer, middleware, rewrites or server actions — which avoids most of them, but upgrading
   to a supported Next.js major (15/16) is strongly recommended.
2. Refresh tokens are kept in `sessionStorage` for reload persistence. For higher assurance, serve web and API from
   the same site and move the refresh token to an `HttpOnly; Secure; SameSite=Strict` cookie.
3. No email verification or password-reset flow yet — add one with your email provider before public signup.
4. Medication checks are limited to allergy name matches and duplicates; integrate a licensed drug database for real interaction checking.
5. Safety-net alert thresholds are generic and must be reviewed by your clinical safety officer.
6. Commission an independent penetration test and complete your jurisdiction's compliance assessment.
