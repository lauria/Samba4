/*
   Unix SMB/CIFS implementation.

   Generic Authentication Interface

   Copyright (C) Andrew Tridgell 2003
   Copyright (C) Andrew Bartlett <abartlet@samba.org> 2004-2006

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

#include "includes.h"
#include "auth/gensec/gensec.h"
#include "auth/auth.h"
#include "auth/system_session_proto.h"

NTSTATUS gensec_generate_session_info(TALLOC_CTX *mem_ctx,
				      struct gensec_security *gensec_security,
				      struct auth_user_info_dc *user_info_dc,
				      struct auth_session_info **session_info)
{
	NTSTATUS nt_status;
	uint32_t session_info_flags = 0;

	if (gensec_security->want_features & GENSEC_FEATURE_UNIX_TOKEN) {
		session_info_flags |= AUTH_SESSION_INFO_UNIX_TOKEN;
	}

	session_info_flags |= AUTH_SESSION_INFO_DEFAULT_GROUPS;
	if (user_info_dc->info->authenticated) {
		session_info_flags |= AUTH_SESSION_INFO_AUTHENTICATED;
	}

	if (gensec_security->auth_context) {
		nt_status = gensec_security->auth_context->generate_session_info(mem_ctx, gensec_security->auth_context,
										 user_info_dc,
										 session_info_flags,
										 session_info);
	} else {
		session_info_flags |= AUTH_SESSION_INFO_SIMPLE_PRIVILEGES;
		nt_status = auth_generate_session_info(mem_ctx,
						       NULL,
						       NULL,
						       user_info_dc, session_info_flags,
						       session_info);
	}
	return nt_status;
}
