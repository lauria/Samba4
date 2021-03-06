/*
   Unix SMB/CIFS implementation.
   Authentication utility functions
   Copyright (C) Sumit Bose 2010

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

#ifndef _RPC_CLIENT_UTIL_LSARPC_H_
#define _RPC_CLIENT_UTIL_LSARPC_H_

/* The following definitions come from rpc_client/util_lsarpc.c  */

NTSTATUS auth_blob_2_auth_info(TALLOC_CTX *mem_ctx,
			       DATA_BLOB incoming, DATA_BLOB outgoing,
			       struct lsa_TrustDomainInfoAuthInfo *auth_info);
NTSTATUS auth_info_2_auth_blob(TALLOC_CTX *mem_ctx,
			       struct lsa_TrustDomainInfoAuthInfo *auth_info,
			       DATA_BLOB *incoming, DATA_BLOB *outgoing);

#endif /* _RPC_CLIENT_UTIL_LSARPC_H_ */
