--
-- PostgreSQL database dump
--

\restrict jbPCC94EGN6MURwrI2QnDrbpv5xoTuxosqc3uhvFEVCXAYrLtTZepD8mGQzip2E

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ai_usage; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ai_usage (
    id character varying(36) NOT NULL,
    tenant_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    conversation_id character varying(36),
    provider character varying(50) NOT NULL,
    model character varying(100) NOT NULL,
    input_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    total_tokens integer NOT NULL,
    estimated_cost double precision NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.ai_usage OWNER TO postgres;

--
-- Name: conversation_messages; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.conversation_messages (
    id character varying(36) NOT NULL,
    conversation_id character varying(36) NOT NULL,
    role character varying(20) NOT NULL,
    content text NOT NULL,
    model character varying(100),
    token_usage json,
    tool_name character varying(100),
    tool_metadata json,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.conversation_messages OWNER TO postgres;

--
-- Name: conversation_summaries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.conversation_summaries (
    id character varying(36) NOT NULL,
    conversation_id character varying(36) NOT NULL,
    summary_text text NOT NULL,
    last_message_id character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.conversation_summaries OWNER TO postgres;

--
-- Name: conversations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.conversations (
    id character varying(36) NOT NULL,
    tenant_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    title character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.conversations OWNER TO postgres;

--
-- Name: knowledge_chunks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.knowledge_chunks (
    id character varying(36) NOT NULL,
    document_id character varying(36) NOT NULL,
    tenant_id character varying(36),
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding json,
    metadata json,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.knowledge_chunks OWNER TO postgres;

--
-- Name: knowledge_documents; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.knowledge_documents (
    id character varying(36) NOT NULL,
    tenant_id character varying(36),
    title character varying(255) NOT NULL,
    category character varying(100) NOT NULL,
    language character varying(10) NOT NULL,
    version character varying(20) NOT NULL,
    status character varying(50) NOT NULL,
    source character varying(255),
    file_path character varying(500),
    file_size bigint NOT NULL,
    mime_type character varying(100) NOT NULL,
    error_message text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.knowledge_documents OWNER TO postgres;

--
-- Name: security_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.security_events (
    id character varying(36) NOT NULL,
    tenant_id character varying(36),
    user_id character varying(36),
    event_type character varying(100) NOT NULL,
    severity character varying(20) NOT NULL,
    request_id character varying(100),
    ip_address character varying(50),
    user_agent character varying(255),
    resource_type character varying(100),
    resource_id character varying(100),
    metadata json,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.security_events OWNER TO postgres;

--
-- Name: support_ticket_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.support_ticket_events (
    id character varying(36) NOT NULL,
    ticket_id character varying(50) NOT NULL,
    event_type character varying(50) NOT NULL,
    actor_id character varying(36) NOT NULL,
    metadata json,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.support_ticket_events OWNER TO postgres;

--
-- Name: support_ticket_messages; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.support_ticket_messages (
    id character varying(36) NOT NULL,
    ticket_id character varying(50) NOT NULL,
    sender_type character varying(20) NOT NULL,
    sender_id character varying(36) NOT NULL,
    message text NOT NULL,
    is_internal boolean NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.support_ticket_messages OWNER TO postgres;

--
-- Name: support_tickets; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.support_tickets (
    id character varying(50) NOT NULL,
    tenant_id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    conversation_id character varying(36),
    subject character varying(255) NOT NULL,
    description text NOT NULL,
    priority character varying(20) NOT NULL,
    status character varying(50) NOT NULL,
    assigned_to character varying(36),
    idempotency_key character varying(100),
    ai_summary json,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    resolved_at timestamp with time zone,
    closed_at timestamp with time zone
);


ALTER TABLE public.support_tickets OWNER TO postgres;

--
-- Name: tenants; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tenants (
    id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    plan character varying(50) NOT NULL,
    connector_tenant_id character varying(100),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.tenants OWNER TO postgres;

--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    id character varying(36) NOT NULL,
    tenant_id character varying(36) NOT NULL,
    connector_user_id character varying(100),
    email character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    role character varying(50) NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Data for Name: ai_usage; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.ai_usage (id, tenant_id, user_id, conversation_id, provider, model, input_tokens, output_tokens, total_tokens, estimated_cost, created_at) FROM stdin;
6310d88c-52ea-4fd2-9f3a-8cef27100cd8	3733647b-374b-404a-8dc8-382b7de1abd3	1e336198-e0dc-4ede-bf84-20165e022c67	b1bf86af-be11-4a81-b1d7-19b7a95681da	patwatoliai	grounded-rules-engine	40	80	120	0.0006	2026-09-22 16:46:14.228163+05:30
\.


--
-- Data for Name: conversation_messages; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.conversation_messages (id, conversation_id, role, content, model, token_usage, tool_name, tool_metadata, created_at) FROM stdin;
51955f2f-86e8-4f51-bbca-78263d41138e	b1bf86af-be11-4a81-b1d7-19b7a95681da	user	Mera Tally connection online hai ya nahi?	\N	\N	\N	\N	2026-09-22 16:46:14.215164+05:30
71692c1d-0bea-4658-8f7a-20e363b4cbaf	b1bf86af-be11-4a81-b1d7-19b7a95681da	assistant	Aapka Tally Prime Connector abhi **LIVE aur CONNECTED** hai!\n\n• **Status**: Online\n• **Port**: 9000 (Tally Prime Default)\n• **Agent Version**: 1.0.1\n\nKya aapko kisi specific company ka data sync check karna hai?	grounded-rules-engine	{"prompt_tokens": 40, "completion_tokens": 80, "total_tokens": 120}	\N	[{"tool": "get_my_connection_status", "result": {"connection_id": "conn_tally_01", "is_online": true, "tally_connected": true, "tally_port": 9000, "agent_version": "1.0.1", "last_heartbeat": "2026-09-22T16:30:00Z"}}]	2026-09-22 16:46:14.22571+05:30
\.


--
-- Data for Name: conversation_summaries; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.conversation_summaries (id, conversation_id, summary_text, last_message_id, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: conversations; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.conversations (id, tenant_id, user_id, title, status, created_at, updated_at) FROM stdin;
b1bf86af-be11-4a81-b1d7-19b7a95681da	3733647b-374b-404a-8dc8-382b7de1abd3	1e336198-e0dc-4ede-bf84-20165e022c67	Mera Tally connection online hai ya nahi...	ACTIVE	2026-09-22 16:46:14.208016+05:30	2026-09-22 16:46:14.208017+05:30
\.


--
-- Data for Name: knowledge_chunks; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.knowledge_chunks (id, document_id, tenant_id, chunk_index, content, embedding, metadata, created_at) FROM stdin;
cbf10b72-f0d2-413e-8fd5-4cf8b1ec7a05	63c80a35-4a34-45d3-8f90-e0ec2730ec67	3733647b-374b-404a-8dc8-382b7de1abd3	0	To configure Tally Prime for Connector synchronization, enable HTTP XML on port 9000.	\N	{"title": "Tally Port 9000 Guide", "category": "Troubleshooting"}	2026-09-22 16:46:14.296088+05:30
\.


--
-- Data for Name: knowledge_documents; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.knowledge_documents (id, tenant_id, title, category, language, version, status, source, file_path, file_size, mime_type, error_message, created_at, updated_at) FROM stdin;
63c80a35-4a34-45d3-8f90-e0ec2730ec67	3733647b-374b-404a-8dc8-382b7de1abd3	Tally Port 9000 Guide	Troubleshooting	en	1.0.0	ACTIVE	\N	\N	85	text/plain	\N	2026-09-22 16:46:14.290467+05:30	2026-09-22 16:46:14.290469+05:30
\.


--
-- Data for Name: security_events; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.security_events (id, tenant_id, user_id, event_type, severity, request_id, ip_address, user_agent, resource_type, resource_id, metadata, created_at) FROM stdin;
\.


--
-- Data for Name: support_ticket_events; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.support_ticket_events (id, ticket_id, event_type, actor_id, metadata, created_at) FROM stdin;
9efdefef-76a9-4088-ab2b-39e0796be3d3	TCK-CF2A1D	CREATED	1e336198-e0dc-4ede-bf84-20165e022c67	{"priority": "HIGH", "has_ai_summary": false}	2026-09-22 16:46:14.270167+05:30
\.


--
-- Data for Name: support_ticket_messages; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.support_ticket_messages (id, ticket_id, sender_type, sender_id, message, is_internal, created_at) FROM stdin;
d7a4694c-ddd7-4688-b9d7-f2ae27d83014	TCK-CF2A1D	USER	1e336198-e0dc-4ede-bf84-20165e022c67	Ledger error encountered during vouchers sync	f	2026-09-22 16:46:14.275342+05:30
\.


--
-- Data for Name: support_tickets; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.support_tickets (id, tenant_id, user_id, conversation_id, subject, description, priority, status, assigned_to, idempotency_key, ai_summary, created_at, updated_at, resolved_at, closed_at) FROM stdin;
TCK-CF2A1D	3733647b-374b-404a-8dc8-382b7de1abd3	1e336198-e0dc-4ede-bf84-20165e022c67	\N	Tally Sync Failed	Ledger error encountered during vouchers sync	HIGH	OPEN	\N	test_idem_99999	null	2026-09-22 16:46:14.266883+05:30	2026-09-22 16:46:14.266886+05:30	\N	\N
\.


--
-- Data for Name: tenants; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tenants (id, name, status, plan, connector_tenant_id, created_at, updated_at) FROM stdin;
3733647b-374b-404a-8dc8-382b7de1abd3	Primary Organization	ACTIVE	Pro	cnt_test_admin	2026-09-22 16:46:14.156622+05:30	2026-09-22 16:46:14.156625+05:30
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (id, tenant_id, connector_user_id, email, name, role, is_active, created_at, updated_at) FROM stdin;
1e336198-e0dc-4ede-bf84-20165e022c67	3733647b-374b-404a-8dc8-382b7de1abd3	usr_test_admin	test_admin@example.com	Amit Sharma	ADMIN	t	2026-09-22 16:46:14.165399+05:30	2026-09-22 16:46:14.165402+05:30
\.


--
-- Name: ai_usage ai_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_usage
    ADD CONSTRAINT ai_usage_pkey PRIMARY KEY (id);


--
-- Name: conversation_messages conversation_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT conversation_messages_pkey PRIMARY KEY (id);


--
-- Name: conversation_summaries conversation_summaries_conversation_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.conversation_summaries
    ADD CONSTRAINT conversation_summaries_conversation_id_key UNIQUE (conversation_id);


--
-- Name: conversation_summaries conversation_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.conversation_summaries
    ADD CONSTRAINT conversation_summaries_pkey PRIMARY KEY (id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: knowledge_chunks knowledge_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_pkey PRIMARY KEY (id);


--
-- Name: knowledge_documents knowledge_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT knowledge_documents_pkey PRIMARY KEY (id);


--
-- Name: security_events security_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_events
    ADD CONSTRAINT security_events_pkey PRIMARY KEY (id);


--
-- Name: support_ticket_events support_ticket_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_ticket_events
    ADD CONSTRAINT support_ticket_events_pkey PRIMARY KEY (id);


--
-- Name: support_ticket_messages support_ticket_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_ticket_messages
    ADD CONSTRAINT support_ticket_messages_pkey PRIMARY KEY (id);


--
-- Name: support_tickets support_tickets_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_tickets
    ADD CONSTRAINT support_tickets_pkey PRIMARY KEY (id);


--
-- Name: tenants tenants_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_ai_usage_conversation_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_ai_usage_conversation_id ON public.ai_usage USING btree (conversation_id);


--
-- Name: ix_ai_usage_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_ai_usage_created_at ON public.ai_usage USING btree (created_at);


--
-- Name: ix_ai_usage_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_ai_usage_tenant_id ON public.ai_usage USING btree (tenant_id);


--
-- Name: ix_ai_usage_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_ai_usage_user_id ON public.ai_usage USING btree (user_id);


--
-- Name: ix_conversation_messages_conversation_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_conversation_messages_conversation_id ON public.conversation_messages USING btree (conversation_id);


--
-- Name: ix_conversations_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_conversations_tenant_id ON public.conversations USING btree (tenant_id);


--
-- Name: ix_conversations_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_conversations_user_id ON public.conversations USING btree (user_id);


--
-- Name: ix_knowledge_chunks_document_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_knowledge_chunks_document_id ON public.knowledge_chunks USING btree (document_id);


--
-- Name: ix_knowledge_chunks_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_knowledge_chunks_tenant_id ON public.knowledge_chunks USING btree (tenant_id);


--
-- Name: ix_knowledge_documents_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_knowledge_documents_tenant_id ON public.knowledge_documents USING btree (tenant_id);


--
-- Name: ix_security_events_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_security_events_created_at ON public.security_events USING btree (created_at);


--
-- Name: ix_security_events_event_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_security_events_event_type ON public.security_events USING btree (event_type);


--
-- Name: ix_security_events_request_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_security_events_request_id ON public.security_events USING btree (request_id);


--
-- Name: ix_security_events_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_security_events_tenant_id ON public.security_events USING btree (tenant_id);


--
-- Name: ix_security_events_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_security_events_user_id ON public.security_events USING btree (user_id);


--
-- Name: ix_support_ticket_events_ticket_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_support_ticket_events_ticket_id ON public.support_ticket_events USING btree (ticket_id);


--
-- Name: ix_support_ticket_messages_ticket_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_support_ticket_messages_ticket_id ON public.support_ticket_messages USING btree (ticket_id);


--
-- Name: ix_support_tickets_assigned_to; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_support_tickets_assigned_to ON public.support_tickets USING btree (assigned_to);


--
-- Name: ix_support_tickets_conversation_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_support_tickets_conversation_id ON public.support_tickets USING btree (conversation_id);


--
-- Name: ix_support_tickets_idempotency_key; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ix_support_tickets_idempotency_key ON public.support_tickets USING btree (idempotency_key);


--
-- Name: ix_support_tickets_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_support_tickets_tenant_id ON public.support_tickets USING btree (tenant_id);


--
-- Name: ix_support_tickets_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_support_tickets_user_id ON public.support_tickets USING btree (user_id);


--
-- Name: ix_tenants_connector_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ix_tenants_connector_tenant_id ON public.tenants USING btree (connector_tenant_id);


--
-- Name: ix_users_connector_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_users_connector_user_id ON public.users USING btree (connector_user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_tenant_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_users_tenant_id ON public.users USING btree (tenant_id);


--
-- Name: ai_usage ai_usage_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_usage
    ADD CONSTRAINT ai_usage_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: ai_usage ai_usage_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ai_usage
    ADD CONSTRAINT ai_usage_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: conversation_messages conversation_messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT conversation_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;


--
-- Name: conversation_summaries conversation_summaries_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.conversation_summaries
    ADD CONSTRAINT conversation_summaries_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;


--
-- Name: conversations conversations_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: conversations conversations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: knowledge_chunks knowledge_chunks_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.knowledge_documents(id) ON DELETE CASCADE;


--
-- Name: knowledge_documents knowledge_documents_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT knowledge_documents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: security_events security_events_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_events
    ADD CONSTRAINT security_events_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: support_ticket_events support_ticket_events_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_ticket_events
    ADD CONSTRAINT support_ticket_events_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.support_tickets(id) ON DELETE CASCADE;


--
-- Name: support_ticket_messages support_ticket_messages_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_ticket_messages
    ADD CONSTRAINT support_ticket_messages_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.support_tickets(id) ON DELETE CASCADE;


--
-- Name: support_tickets support_tickets_assigned_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_tickets
    ADD CONSTRAINT support_tickets_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: support_tickets support_tickets_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_tickets
    ADD CONSTRAINT support_tickets_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE SET NULL;


--
-- Name: support_tickets support_tickets_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_tickets
    ADD CONSTRAINT support_tickets_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: support_tickets support_tickets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.support_tickets
    ADD CONSTRAINT support_tickets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict jbPCC94EGN6MURwrI2QnDrbpv5xoTuxosqc3uhvFEVCXAYrLtTZepD8mGQzip2E

