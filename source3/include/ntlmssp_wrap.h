/*
   NLTMSSP wrappers

   Copyright (C) Andrew Tridgell      2001
   Copyright (C) Andrew Bartlett 2001-2003

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#ifndef _NTLMSSP_WRAP_
#define _NTLMSSP_WRAP_

struct gensec_security;

struct auth_ntlmssp_state {
	/* used only by server implementation */
	struct auth_context *auth_context;
	
	/* used only by the client implementation */
	struct cli_credentials *credentials;

	/* used by both */
	struct gensec_security *gensec_security;
};

NTSTATUS auth_ntlmssp_set_username(struct auth_ntlmssp_state *ans,
				   const char *user);
NTSTATUS auth_ntlmssp_set_domain(struct auth_ntlmssp_state *ans,
				 const char *domain);
NTSTATUS auth_ntlmssp_set_password(struct auth_ntlmssp_state *ans,
				   const char *password);
NTSTATUS auth_ntlmssp_client_prepare(TALLOC_CTX *mem_ctx,
				     struct auth_ntlmssp_state **_ans);
NTSTATUS auth_ntlmssp_client_start(struct auth_ntlmssp_state *ans);

#endif /* _NTLMSSP_WRAP_ */
