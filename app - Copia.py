import streamlit as st
import pandas as pd
import re
import json
import io
from datetime import datetime, date
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
import plotly.express as px
import time

# --- CONFIGURAÇÃO E CONSTANTES ---
st.set_page_config(page_title="SST - Pesquisas", layout="wide", initial_sidebar_state="expanded")

# --- OCULTAR ELEMENTOS DO STREAMLIT ---
hide_st_style = """
            <style>
            .stAppDeployButton {display: none !important;}
            [data-testid="stDeployButton"] {display: none !important;}
            #MainMenu {visibility: hidden !important;}
            footer {visibility: hidden !important;}
            [data-testid="stFooter"] {display: none !important;}
            [data-testid="stToolbar"] {display: none !important;}
            [data-testid="stDecoration"] {display: none !important;}
            [data-testid="hostedWatermark"] {display: none !important;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- BANCO DE DADOS ---
DB_URL = st.secrets["db_url"] if "db_url" in st.secrets else "sqlite:///sst_data.db"
Base = declarative_base()

class Empresa(Base):
    __tablename__ = 'empresas'
    id = Column(Integer, primary_key=True)
    codigo_empresa = Column(String(50), unique=True, nullable=False)
    nome_empresa = Column(String(200), nullable=False)
    senha_rh = Column(String(100), nullable=False) 
    link_forms = Column(String(500), nullable=False)
    funcionarios = relationship("Funcionario", back_populates="empresa", cascade="all, delete-orphan")

class Questionario(Base):
    __tablename__ = 'questionarios'
    id = Column(Integer, primary_key=True)
    nome = Column(String(200), nullable=False)
    descricao = Column(String(500))
    perguntas = relationship("Pergunta", back_populates="questionario", cascade="all, delete-orphan")
    campanhas = relationship("Campanha", back_populates="questionario", cascade="all, delete-orphan")

class Pergunta(Base):
    __tablename__ = 'perguntas'
    id = Column(Integer, primary_key=True)
    questionario_id = Column(Integer, ForeignKey('questionarios.id'), nullable=False)
    ordem = Column(Integer, default=0)
    dimensao = Column(String(200))
    enunciado = Column(String(500), nullable=False)
    texto_ajuda = Column(String(500))
    inverter_pontuacao = Column(Integer, default=0) 
    tipo_pergunta = Column(String(50), default="escala")
    opcoes_json = Column(String(1000), nullable=False) 
    questionario = relationship("Questionario", back_populates="perguntas")

class Campanha(Base):
    __tablename__ = 'campanhas'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey('empresas.id'), nullable=False)
    questionario_id = Column(Integer, ForeignKey('questionarios.id'), nullable=False)
    nome_campanha = Column(String(200), nullable=False)
    data_inicio = Column(String(20), default=lambda: datetime.now().strftime('%d/%m/%Y'))
    status = Column(String(50), default="Ativa")
    questionario = relationship("Questionario", back_populates="campanhas")
    empresa = relationship("Empresa")

class Funcionario(Base):
    __tablename__ = 'funcionarios'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey('empresas.id'), nullable=False)
    cpf = Column(String(20), nullable=False)
    nome = Column(String(200), nullable=False)
    data_nasc = Column(String(20), nullable=False)
    setor = Column(String(100))
    funcao = Column(String(100))
    status = Column(String(50), default="Pendente")
    ativo = Column(Boolean, default=True)
    empresa = relationship("Empresa", back_populates="funcionarios")
    sessao_pesquisa = relationship("SurveySession", backref="funcionario", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint('empresa_id', 'cpf', name='_empresa_cpf_uc'),)

class SurveySession(Base):
    __tablename__ = 'survey_sessions'
    id = Column(Integer, primary_key=True)
    funcionario_id = Column(Integer, ForeignKey('funcionarios.id'), nullable=False)
    campanha_id = Column(Integer, ForeignKey('campanhas.id'), nullable=True)
    data_criacao = Column(String(20), default=lambda: datetime.now().strftime('%d/%m/%Y %H:%M:%S'))
    respostas = relationship("Answer", back_populates="sessao", cascade="all, delete-orphan")
    campanha = relationship("Campanha")

class Answer(Base):
    __tablename__ = 'answers'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('survey_sessions.id'), nullable=False)
    pergunta_id = Column(Integer, nullable=False)
    resposta_texto = Column(String(1000), nullable=False)
    sessao = relationship("SurveySession", back_populates="respostas")

@st.cache_resource
def get_engine():
    return create_engine(DB_URL, pool_pre_ping=True, pool_recycle=3600)

engine = get_engine()
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    return SessionLocal()

# --- UTILITÁRIOS ---
def limpar_cpf(cpf):
    if pd.isna(cpf) or str(cpf).strip() == "":
        return ""
    return re.sub(r'\D', '', str(cpf))

def processar_data_robusta(valor):
    if pd.isna(valor) or str(valor).strip() == "":
        return ""
    try:
        if isinstance(valor, (date, datetime)):
            return valor.strftime('%d/%m/%Y')
        dt = pd.to_datetime(valor, dayfirst=True, errors='coerce')
        if pd.isna(dt):
            return ""
        return dt.strftime('%d/%m/%Y')
    except:
        return ""

# --- COMPONENTES DE UI ---
def login_colaborador(empresa):
    st.title(f"Acesso: {empresa.nome_empresa}")
    st.info("Valide seus dados para acessar o formulário.")
    
    with st.form("login_worker"):
        cpf_input = st.text_input("CPF (apenas números)")
        data_nasc_input = st.date_input("Data de Nascimento", value=None, min_value=datetime(1940, 1, 1), format="DD/MM/YYYY")
        
        if st.form_submit_button("ENTRAR"):
            db = get_db()
            cpf_clean = limpar_cpf(cpf_input)
            data_str = processar_data_robusta(data_nasc_input)
            
            user = db.query(Funcionario).filter(
                Funcionario.empresa_id == empresa.id, 
                Funcionario.cpf == cpf_clean, 
                Funcionario.data_nasc == data_str
            ).first()
            
            if user:
                if not user.ativo:
                    st.error("Acesso desativado. Procure o RH da sua empresa.")
                elif user.status == "Concluído":
                    st.success(f"Olá {user.nome}! Você já concluiu seu preenchimento. Obrigado!")
                    st.balloons()
                else:
                    st.session_state['logged_user_id'] = user.id
                    st.rerun()
            else:
                st.error("Dados não encontrados. Verifique seu CPF e Data de Nascimento.")

def renderizar_questionario_dinamico(user, campanha):
    if 'tentou_enviar' not in st.session_state: 
        st.session_state.tentou_enviar = False

    st.title(f"📋 {campanha.questionario.nome}")
    if campanha.questionario.descricao:
        st.info(campanha.questionario.descricao)
    
    st.write("Por favor, responda a todas as perguntas abaixo com sinceridade.")
    
    db = get_db()
    perguntas = db.query(Pergunta).filter(Pergunta.questionario_id == campanha.questionario_id).order_by(Pergunta.ordem.asc(), Pergunta.id.asc()).all()
    
    if not perguntas:
        st.warning("Este questionário ainda não possui perguntas cadastradas.")
        return

    respostas_usuario = {}
    
    for p in perguntas:
        key_p = f"q_{p.id}_{campanha.id}"
        val_atual = st.session_state.get(key_p)
        esta_vazio = val_atual is None or str(val_atual).strip() == ""

        with st.container(border=True):
            if st.session_state.tentou_enviar and esta_vazio:
                st.error("⚠️ Esta pergunta é obrigatória.")

            st.markdown(f"**{p.ordem}. {p.enunciado}**")
            if p.texto_ajuda:
                st.caption(f"💡 Ajuda: {p.texto_ajuda}")
            
            if p.tipo_pergunta == "texto":
                respostas_usuario[p.id] = st.text_area(
                    f"Resposta para {p.id}", 
                    key=key_p, 
                    label_visibility="collapsed",
                    placeholder="Digite sua resposta aqui..."
                )
            else:
                try: opcoes = json.loads(p.opcoes_json)
                except: opcoes = {"1": "Erro na carga das opções"}
                
                opcoes_keys = sorted([int(k) for k in opcoes.keys()])
                
                if p.tipo_pergunta == "lista":
                    respostas_usuario[p.id] = st.selectbox(
                        f"Resposta para {p.id}",
                        options=opcoes_keys,
                        index=None,
                        format_func=lambda x: f"{x} - {opcoes.get(str(x), '')}",
                        key=key_p,
                        label_visibility="collapsed"
                    )
                else: 
                    respostas_usuario[p.id] = st.radio(
                        f"Resposta para {p.id}",
                        options=opcoes_keys,
                        index=None,
                        format_func=lambda x: f"{x} - {opcoes.get(str(x), '')}",
                        horizontal=False,
                        key=key_p,
                        label_visibility="collapsed"
                    )

    st.divider()
    if st.button("🚀 ENVIAR RESPOSTAS", use_container_width=True, type="primary"):
        st.session_state.tentou_enviar = True
        if any(v is None or str(v).strip() == "" for v in respostas_usuario.values()):
            st.error("Por favor, responda a todas as perguntas destacadas em vermelho.")
            st.rerun()
            return
            
        try:
            nova_sessao = SurveySession(funcionario_id=user.id, campanha_id=campanha.id)
            db.add(nova_sessao)
            db.flush() 
            
            for p_id, valor in respostas_usuario.items():
                db.add(Answer(session_id=nova_sessao.id, pergunta_id=p_id, resposta_texto=str(valor)))
            
            db_user = db.query(Funcionario).filter(Funcionario.id == user.id).first()
            db_user.status = "Concluído"
            
            db.commit()
            st.success("Questionário enviado com sucesso!")
            st.balloons()
            st.session_state.tentou_enviar = False
            st.session_state.pop('logged_user_id', None)
            st.rerun()
        except Exception as e:
            db.rollback()
            st.error(f"Erro ao salvar: {e}")
        finally:
            db.close()

def portal_colaborador(empresa, user):
    db = get_db()
    campanha_ativa = db.query(Campanha).filter(
        Campanha.empresa_id == empresa.id,
        Campanha.status == "Ativa"
    ).first()
    
    if not campanha_ativa:
        st.title(f"Olá, {user.nome}")
        st.info("Não há nenhuma campanha de pesquisa ativa para sua empresa no momento.")
        return
    renderizar_questionario_dinamico(user, campanha_ativa)

# --- ÁREA ADMINISTRATIVA ---
def admin_portal():
    st.sidebar.title("🛡️ Admin Master")
    if 'admin_logged_in' not in st.session_state:
        with st.sidebar.form("admin_login"):
            user = st.text_input("Usuário")
            pw = st.text_input("Senha", type="password")
            if st.form_submit_button("Acessar Master"):
                if user == st.secrets["admin_user"] and pw == st.secrets["admin_password"]:
                    st.session_state['admin_logged_in'] = True
                    st.rerun()
                else:
                    st.error("Credenciais inválidas")
        return

    db = get_db()
    empresas_base = db.query(Empresa).order_by(Empresa.nome_empresa.asc()).all()
    lista_contextos = ["[Administração Geral]"] + [e.nome_empresa for e in empresas_base]
    contexto = st.sidebar.selectbox("🏢 Contexto da Empresa", lista_contextos)
    
    if contexto == "[Administração Geral]":
        menu = st.sidebar.radio("Navegação", ["Dashboard Global", "Gestão de Empresas", "Bancos de Questionários", "Sair"])
    else:
        empresa_selecionada = next(e for e in empresas_base if e.nome_empresa == contexto)
        emp_id = empresa_selecionada.id
        menu = st.sidebar.radio(f"Navegação: {contexto}", ["👥 Funcionários", "📊 Campanhas e Resultados", "Sair"])

    if menu == "Sair":
        st.session_state.pop('admin_logged_in')
        st.rerun()

    if contexto == "[Administração Geral]":
        if menu == "Dashboard Global":
            st.title("📊 Painel de Engajamento Global")
            c1, c2 = st.columns(2)
            campanhas_all = db.query(Campanha).all()
            camp_names = list(set([c.nome_campanha for c in campanhas_all]))
            sel_camp = c2.selectbox("Filtrar por Campanha", ["Todas"] + camp_names)
            
            funcionarios = db.query(Funcionario).all()
            if funcionarios:
                rows = []
                for f in funcionarios:
                    st_f = f.status
                    if sel_camp != "Todas":
                        camp = db.query(Campanha).filter_by(nome_campanha=sel_camp).first()
                        if camp:
                            sessao = db.query(SurveySession).filter_by(funcionario_id=f.id, campanha_id=camp.id).first()
                            st_f = "Concluído" if sessao else "Pendente"
                    rows.append({'Status': st_f})
                
                df = pd.DataFrame(rows)
                c1, c2, c3 = st.columns(3)
                total = len(df); concluidos = len(df[df['Status'] == 'Concluído'])
                c1.metric("Total de Vidas", total)
                c2.metric("Total Respostas", concluidos)
                c3.metric("Engajamento Médio", f"{(concluidos/total*100):.1f}%" if total > 0 else "0%")
                st.plotly_chart(px.pie(df, names='Status', color='Status', color_discrete_map={'Concluído':'#22c55e', 'Pendente':'#ef4444'}), use_container_width=True)
            else: st.info("Nenhum dado global disponível.")

        elif menu == "Gestão de Empresas":
            st.title("🏢 Gestão de Empresas")
            with st.expander("➕ Cadastrar Nova Empresa"):
                with st.form("new_company"):
                    c1, c2 = st.columns(2)
                    codigo = c1.text_input("Código URL (ex: empresa-teste)")
                    nome = c2.text_input("Nome da Empresa")
                    link = st.text_input("Link do Google Forms")
                    senha = st.text_input("Senha do RH", type="password")
                    if st.form_submit_button("Salvar Empresa"):
                        if db.query(Empresa).filter_by(codigo_empresa=codigo).first(): st.error("Código já existe!")
                        else:
                            db.add(Empresa(codigo_empresa=codigo, nome_empresa=nome, link_forms=link, senha_rh=senha))
                            db.commit(); st.success("Empresa cadastrada!"); st.rerun()

            empresas = db.query(Empresa).order_by(Empresa.nome_empresa.asc()).all()
            df_emp = pd.DataFrame([{'id': e.id, 'Nome': e.nome_empresa, 'Código': e.codigo_empresa, 'Senha RH': e.senha_rh, 'Link': e.link_forms} for e in empresas])
            if df_emp.empty: df_emp = pd.DataFrame(columns=['id', 'Nome', 'Código', 'Senha RH', 'Link'])
            else: df_emp = df_emp.sort_values(by='Nome', ignore_index=True)

            ed_emp = st.data_editor(df_emp, key="ed_emp", num_rows="dynamic", use_container_width=True, disabled=["id"], column_config={"id": None})
            if st.button("💾 Salvar Alterações"):
                ids_orig = set(df_emp['id'].dropna()); ids_atuais = set(ed_emp['id'].dropna())
                for id_del in (ids_orig - ids_atuais):
                    e_del = db.query(Empresa).get(int(id_del))
                    if e_del: db.delete(e_del)
                for _, row in ed_emp.iterrows():
                    if pd.notna(row.get('id')):
                        e_db = db.query(Empresa).get(int(row['id']))
                        if e_db:
                            e_db.nome_empresa, e_db.codigo_empresa, e_db.senha_rh, e_db.link_forms = str(row['Nome']), str(row['Código']), str(row['Senha RH']), str(row['Link'])
                    elif pd.notna(row.get('Nome')):
                        db.add(Empresa(nome_empresa=str(row['Nome']), codigo_empresa=str(row['Código']), senha_rh=str(row['Senha RH']), link_forms=str(row['Link'])))
                db.commit(); st.success("Empresas atualizadas!"); st.rerun()

        elif menu == "Bancos de Questionários":
            st.title("📚 Bancos de Questionários")
            with st.expander("➕ Criar Novo Questionário"):
                with st.form("new_q"):
                    nome_q = st.text_input("Nome do Questionário")
                    desc_q = st.text_area("Descrição")
                    if st.form_submit_button("Criar"):
                        if nome_q: db.add(Questionario(nome=nome_q, descricao=desc_q)); db.commit(); st.success("Criado!"); st.rerun()
            
            qs = db.query(Questionario).all()
            for q in qs:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"### {q.nome}")
                    if c2.button("Excluir", key=f"del_q_{q.id}"): db.delete(q); db.commit(); st.rerun()
                    st.write(q.descricao)
                    with st.expander("Perguntas"):
                        if q.perguntas:
                            df_bkp = pd.DataFrame([{'Ordem': p.ordem, 'Enunciado': p.enunciado, 'Ajuda': p.texto_ajuda, 'Dimensão': p.dimensao, 'Tipo': p.tipo_pergunta, 'Opcoes': p.opcoes_json} for p in q.perguntas])
                            buf = io.BytesIO(); df_bkp.to_excel(buf, index=False)
                            st.download_button("📥 Exportar Backup", buf.getvalue(), f"backup_q_{q.id}.xlsx", key=f"bkp_{q.id}")
                            st.divider()
                        
                        rows_p = [{'id': p.id, 'Ordem': p.ordem, 'Enunciado': p.enunciado, 'Ajuda': p.texto_ajuda, 'Dimensão': p.dimensao, 'Tipo': p.tipo_pergunta, 'Opções': p.opcoes_json} for p in q.perguntas]
                        df_p = pd.DataFrame(rows_p) if rows_p else pd.DataFrame(columns=['id', 'Ordem', 'Enunciado', 'Ajuda', 'Dimensão', 'Tipo', 'Opções'])
                        ed_p = st.data_editor(df_p.sort_values(by=['Ordem', 'id'], ignore_index=True) if not df_p.empty else df_p, key=f"ed_p_{q.id}", num_rows="dynamic", use_container_width=True, disabled=["id"], column_config={"id": None, "Ordem": st.column_config.NumberColumn(step=1), "Tipo": st.column_config.SelectboxColumn(options=["escala", "lista", "texto"])})
                        
                        if st.button("💾 Salvar Perguntas", key=f"sv_p_{q.id}"):
                            ids_b = {p.id for p in q.perguntas}; ids_t = set(pd.to_numeric(ed_p['id'], errors='coerce').dropna().astype(int))
                            for id_d in (ids_b - ids_t):
                                p_d = db.query(Pergunta).get(id_d)
                                if p_d: db.delete(p_d)
                            for _, r in ed_p.iterrows():
                                if pd.notna(r.get('id')):
                                    p_db = db.query(Pergunta).get(int(r['id']))
                                    if p_db: p_db.ordem, p_db.enunciado, p_db.texto_ajuda, p_db.dimensao, p_db.tipo_pergunta, p_db.opcoes_json = int(r.get('Ordem', 0)), str(r['Enunciado']), str(r.get('Ajuda', '')), str(r.get('Dimensão', '')), str(r.get('Tipo', 'escala')), str(r.get('Opções', '{}'))
                                elif pd.notna(r.get('Enunciado')):
                                    db.add(Pergunta(questionario_id=q.id, ordem=int(r.get('Ordem', 0)), enunciado=str(r['Enunciado']), texto_ajuda=str(r.get('Ajuda', '')), dimensao=str(r.get('Dimensão', '')), tipo_pergunta=str(r.get('Tipo', 'escala')), opcoes_json=str(r.get('Opções', '{"1":"Nunca","2":"Sempre"}'))))
                            db.commit(); st.success("Salvo!"); st.rerun()

                        st.divider(); tab_m, tab_l = st.tabs(["✍️ Manual", "📥 Em Lote"])
                        with tab_m:
                            with st.form(f"fm_p_{q.id}"):
                                o, en, aj, di = st.number_input("Ordem", min_value=0), st.text_input("Enunciado"), st.text_input("Ajuda"), st.text_input("Dimensão")
                                ti = st.selectbox("Tipo", ["Escala (Bolinhas)", "Lista Suspensa", "Texto Livre"])
                                op = st.text_area("Opções (JSON)", value='{"1": "Nunca", "2": "Sempre"}')
                                if st.form_submit_button("Adicionar"):
                                    t_m = {"Escala (Bolinhas)": "escala", "Lista Suspensa": "lista", "Texto Livre": "texto"}
                                    db.add(Pergunta(questionario_id=q.id, ordem=o, enunciado=en, texto_ajuda=aj, dimensao=di, tipo_pergunta=t_m[ti], opcoes_json=op))
                                    db.commit(); st.rerun()
                        with tab_l:
                            up_q = st.file_uploader("Upload Excel", type=['csv', 'xlsx'], key=f"up_{q.id}")
                            if up_q:
                                df_q = pd.read_csv(up_q) if up_q.name.endswith('.csv') else pd.read_excel(up_q)
                                if st.button("Confirmar", key=f"cf_{q.id}"):
                                    for i, r in df_q.iterrows():
                                        db.add(Pergunta(questionario_id=q.id, ordem=i+1, enunciado=str(r.iloc[0]), texto_ajuda=str(r.iloc[1]) if len(r)>1 else "", dimensao=str(r.iloc[2]) if len(r)>2 else "", tipo_pergunta=str(r.iloc[3]).lower() if len(r)>3 else "escala", opcoes_json=str(r.iloc[4]) if len(r)>4 else '{"1":"Nunca","2":"Sempre"}'))
                                    db.commit(); st.rerun()

    else:
        if menu == "👥 Funcionários":
            st.title(f"👥 Funcionários: {contexto}")
            with st.expander("📥 Importar Lista"):
                up = st.file_uploader("Excel/CSV", type=['csv', 'xlsx'])
                if up:
                    df_up = pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)
                    if st.button("Confirmar Importação"):
                        count = 0
                        for _, r in df_up.iterrows():
                            cpf = limpar_cpf(r.get('CPF', ''))
                            if cpf and not db.query(Funcionario).filter_by(empresa_id=emp_id, cpf=cpf).first():
                                db.add(Funcionario(empresa_id=emp_id, nome=str(r.get('Nome','')), cpf=cpf, data_nasc=processar_data_robusta(r.get('Nascimento','')), setor=str(r.get('Setor','')), funcao=str(r.get('Função',''))))
                                count += 1
                        db.commit(); st.success(f"{count} importados!"); st.rerun()

            funcs = db.query(Funcionario).filter_by(empresa_id=emp_id).order_by(Funcionario.nome.asc()).all()
            df_f = pd.DataFrame([{'id': f.id, 'Ativo': f.ativo, 'Nome': f.nome, 'CPF': f.cpf, 'Nascimento': f.data_nasc, 'Setor': f.setor, 'Função': f.funcao, 'Status': f.status, 'Resetar': False} for f in funcs])
            if not df_f.empty:
                df_f = df_f.sort_values(by='Nome', ignore_index=True)
                ed_f = st.data_editor(df_f, key="ed_f", num_rows="dynamic", use_container_width=True, disabled=["id", "Status"], column_config={"id": None})
                if st.button("💾 Salvar Alterações"):
                    ids_o = set(df_f['id'].dropna()); ids_a = set(ed_f['id'].dropna())
                    for id_d in (ids_o - ids_a):
                        f_d = db.query(Funcionario).get(int(id_d))
                        if f_d: db.delete(f_d)
                    for _, r in ed_f.iterrows():
                        if pd.notna(r.get('id')):
                            f = db.query(Funcionario).get(int(r['id']))
                            if f:
                                f.ativo, f.nome, f.cpf, f.data_nasc, f.setor, f.funcao = bool(r.get('Ativo', True)), str(r['Nome']), limpar_cpf(r['CPF']), processar_data_robusta(r['Nascimento']), str(r.get('Setor', '')), str(r.get('Função', ''))
                                if r.get('Resetar'):
                                    for s in db.query(SurveySession).filter_by(funcionario_id=f.id).all(): db.delete(s)
                                    f.status = "Pendente"
                        elif pd.notna(r.get('Nome')):
                            db.add(Funcionario(empresa_id=emp_id, nome=str(r['Nome']), cpf=limpar_cpf(r['CPF']), data_nasc=processar_data_robusta(r['Nascimento']), setor=str(r.get('Setor','')), funcao=str(r.get('Função',''))))
                    db.commit(); st.success("Salvo!"); st.rerun()

        elif menu == "📊 Campanhas e Resultados":
            st.title(f"📊 Campanhas e Resultados: {contexto}")
            with st.expander("🚀 Iniciar Nova Campanha"):
                with st.form("nc"):
                    qs = {q.nome: q.id for q in db.query(Questionario).all()}
                    sel_q = st.selectbox("Questionário", list(qs.keys()))
                    n_c = st.text_input("Nome da Campanha")
                    if st.form_submit_button("Iniciar"):
                        db.add(Campanha(empresa_id=emp_id, questionario_id=qs[sel_q], nome_campanha=n_c))
                        db.commit(); st.success("Iniciada!"); st.rerun()

            camps = db.query(Campanha).filter_by(empresa_id=emp_id).all()
            if not camps: st.info("Nenhuma campanha ativa.")
            else:
                c_dict = {c.nome_campanha: c.id for c in camps}
                sel_c_id = st.selectbox("Selecione a Campanha para Analisar", list(c_dict.keys()), key="sel_camp_ana")
                sel_c_id = c_dict[sel_c_id]
                c_obj = db.query(Campanha).get(sel_c_id)
                
                tab_exec, tab_estat, tab_ger, tab_bruto = st.tabs(["📊 Relatório Executivo", "📈 Estatísticas", "⚙️ Gerenciar", "📥 Dados Brutos"])
                
                # --- QUERY BASE ---
                res = db.query(Funcionario.setor, Funcionario.funcao, Pergunta.dimensao, Pergunta.enunciado, Pergunta.inverter_pontuacao, Answer.resposta_texto, Funcionario.cpf, Funcionario.id, Pergunta.opcoes_json, Pergunta.ordem)\
                    .join(SurveySession, Answer.session_id == SurveySession.id)\
                    .join(Funcionario, SurveySession.funcionario_id == Funcionario.id)\
                    .join(Pergunta, Answer.pergunta_id == Pergunta.id)\
                    .filter(SurveySession.campanha_id == sel_c_id).all()
                
                df_b = pd.DataFrame(res, columns=['Setor', 'Função', 'Dimensao', 'Enunciado', 'Inverter', 'Resposta', 'CPF', 'FuncID', 'OpcoesJSON', 'Ordem']) if res else pd.DataFrame()
                df_raw = df_b.copy()
                
                with tab_ger:
                    c1, c2 = st.columns(2)
                    c1.write(f"**Status: {c_obj.status}**")
                    if c_obj.status == "Ativa" and st.button("🔴 Encerrar Campanha"):
                        c_obj.status = "Encerrada"; db.commit(); st.rerun()
                    if st.button("🗑️ Excluir Campanha"):
                        db.delete(c_obj); db.commit(); st.rerun()

                if df_b.empty: st.warning("Aguardando primeiras respostas...")
                else:

                    # --- ABA ESTATÍSTICAS (PÁGINA VERTICAL/PORTRAIT) ---
                    with tab_estat:
                        st.markdown("""
                        <style>
                        @media print {
                            /* FORÇA O RETRATO (PORTRAIT) NESTA ABA */
                            @page { size: A4 portrait !important; margin: 15mm !important; }
                            body { zoom: 1.0 !important; }
                            header, footer, [data-testid="stSidebar"], [data-testid="stHeader"], .stButton { display: none !important; }
                            h1, [data-testid="stExpander"], [data-testid="stSelectbox"], div[data-baseweb="tab-list"], .no-print { display: none !important; }
                            .appview-container, .stApp, .main, .block-container { 
                                max-width: 100% !important; padding-top: 0 !important; margin-top: 0 !important; padding-bottom: 0 !important;
                            }
                            div[data-testid="stVerticalBlock"] > div:first-child { padding-top: 0 !important; }
                            * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
                            .barra-bg { background-color: #e6e6e6 !important; }
                            .barra-fill { background-color: #1560bd !important; }
                        }
                        </style>
                        """, unsafe_allow_html=True)

                        if st.button("🖨️ Imprimir Estatísticas"):
                            script = f"<script>window.parent.print();</script><div style='display:none;'>{time.time()}</div>"
                            st.components.v1.html(script, height=0)

                        st.markdown(f"""
                        <div style='text-align: center; margin-bottom: 30px; line-height: 1.2;'>
                            <span style='color: black; font-size: 28px; font-weight: bold;'>Relatório Psicossocial - Estatísticas</span><br>
                            <span style='color: black; font-size: 20px; font-weight: bold;'>{contexto}</span><br>
                            <span style='color: #666; font-size: 16px;'>Campanha: {c_obj.nome_campanha}</span>
                        </div>
                        """, unsafe_allow_html=True)

                        ordem_dimensoes = df_raw.groupby('Dimensao')['Ordem'].min().sort_values().index.tolist()
                        for dim in ordem_dimensoes:
                            df_dim = df_raw[df_raw['Dimensao'] == dim]
                            st.markdown(f"<h3 style='color: #161B4B; border-bottom: 2px solid #1560bd; padding-bottom: 5px; margin-top: 30px; page-break-after: avoid;'>{dim}</h3>", unsafe_allow_html=True)
                            perguntas_dim = df_dim[['Ordem', 'Enunciado', 'OpcoesJSON']].drop_duplicates().sort_values('Ordem')
                            for _, p in perguntas_dim.iterrows():
                                enunciado = p['Enunciado']
                                try: opcoes_dict = json.loads(p['OpcoesJSON'])
                                except: opcoes_dict = {}
                                df_resp = df_dim[df_dim['Enunciado'] == enunciado]
                                total_resp = len(df_resp)
                                st.markdown(f"<div style='font-size: 16px; font-weight: bold; color: black; margin-top: 15px; margin-bottom: 10px; page-break-after: avoid;'>{p['Ordem']}. {enunciado}</div>", unsafe_allow_html=True)
                                
                                html_barras = "<div style='margin-bottom: 25px; page-break-inside: avoid;'>"
                                chaves_ordenadas = sorted([k for k in opcoes_dict.keys() if k.isdigit()], key=int)
                                for k in chaves_ordenadas:
                                    texto_opcao = opcoes_dict[str(k)]
                                    qtd = len(df_resp[df_resp['Resposta'].astype(str) == str(k)])
                                    perc = (qtd / total_resp * 100) if total_resp > 0 else 0
                                    
                                    # CÓDIGO CORRIGIDO: LINHAS SEM ESPAÇOS INVISÍVEIS PARA EVITAR BUG DO MARKDOWN
                                    html_barras += f"<div style='display: flex; align-items: center; margin-bottom: 6px;'>"
                                    html_barras += f"<div style='width: 35%; font-size: 14px; color: #333;'>{texto_opcao}</div>"
                                    html_barras += f"<div class='barra-bg' style='width: 55%; background-color: #e6e6e6; border-radius: 4px; height: 18px; margin: 0 10px; position: relative; overflow: hidden; -webkit-print-color-adjust: exact;'>"
                                    html_barras += f"<div class='barra-fill' style='background-color: #1560bd; width: {perc}%; height: 100%; border-radius: 4px; -webkit-print-color-adjust: exact;'></div>"
                                    html_barras += f"</div>"
                                    html_barras += f"<div style='width: 10%; font-size: 14px; color: black; font-weight: bold; text-align: right;'>{perc:.1f}%</div>"
                                    html_barras += f"</div>"
                                
                                html_barras += "</div>"
                                st.markdown(html_barras, unsafe_allow_html=True)

                    # --- ABA EXECUTIVA (PÁGINA DEITADA/LANDSCAPE) ---
                    df_b['Resposta'] = pd.to_numeric(df_b['Resposta'], errors='coerce')
                    def calc_score(r, inv):
                        if pd.isna(r) or r < 1 or r > 5: return None
                        if inv == 1: return {1:100, 2:75, 3:50, 4:25, 5:0}.get(r)
                        return {1:0, 2:25, 3:50, 4:75, 5:100}.get(r)
                    df_b['Score'] = df_b.apply(lambda x: calc_score(x['Resposta'], x['Inverter']), axis=1)
                    df_s = df_b.dropna(subset=['Score'])
                    def classificar_risco(v):
                        if v <= 49.99: return 'BAIXO', '#22c55e'
                        if v <= 74.99: return 'MODERADO', '#eab308'
                        return 'ALTO', '#ef4444'

                    with tab_exec:
                        st.markdown("""
                        <style>
                        @media print {
                            /* FORÇA A PAISAGEM (LANDSCAPE) NESTA ABA */
                            @page { size: A4 landscape !important; margin: 10mm !important; }
                            body { zoom: 1.0 !important; }
                            header, footer, [data-testid="stSidebar"], [data-testid="stHeader"], .stButton { display: none !important; }
                            h1, [data-testid="stExpander"], [data-testid="stSelectbox"], div[data-baseweb="tab-list"], .no-print { display: none !important; }
                            .appview-container, .stApp, .main, .block-container { 
                                max-width: 100% !important; padding-top: 0 !important; margin-top: 0 !important; padding-bottom: 0 !important;
                            }
                            div[data-testid="stVerticalBlock"] > div:first-child { padding-top: 0 !important; }
                            * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
                            h2, h3 { color: black !important; page-break-after: avoid !important; break-after: avoid !important; }
                            table { color: black !important; }
                            [data-testid="stTable"], table, th, td, [data-testid="stPlotlyChart"] { opacity: 1 !important; }
                            [data-testid="stTable"] { zoom: 0.50 !important; }
                            [data-testid="column"] { zoom: 0.60 !important; }
                            [data-testid="stVerticalBlock"] > div > [data-testid="stPlotlyChart"] { zoom: 0.70 !important; }
                            .force-page-break-before { page-break-before: always !important; break-before: page !important; }
                            .page-break { page-break-after: always !important; break-after: page !important; }
                        }
                        </style>
                        """, unsafe_allow_html=True)

                        if st.button("🖨️ Imprimir / Guardar como PDF"):
                            script = f"<script>window.parent.print();</script><div style='display:none;'>{time.time()}</div>"
                            st.components.v1.html(script, height=0)

                        st.markdown("<div style='page-break-before: always;'></div>", unsafe_allow_html=True)
                        st.markdown(f"""
                        <div style='text-align: center; margin-bottom: 20px; line-height: 1.2;'>
                            <span style='color: black; font-size: 32px; font-weight: bold;'>Relatório de Risco Psicossocial</span><br>
                            <span style='color: black; font-size: 24px; font-weight: bold;'>{contexto}</span>
                        </div>
                        """, unsafe_allow_html=True)

                        df_ado = df_s[df_s['Dimensao'].isin(['Saúde Geral', 'Burnout', 'Estresse', 'Problemas de Sono'])]
                        perc_ado = (df_ado.groupby('FuncID')['Score'].mean().round(2) > 60).mean() * 100 if not df_ado.empty else 0
                        df_ofe = df_b[df_b['Dimensao'] == 'Comportamentos Ofensivos']
                        perc_ofe = (df_ofe[df_ofe['Resposta'] > 1]['CPF'].nunique() / df_s['CPF'].nunique()) * 100 if not df_ofe.empty else 0

                        st.markdown(f"""
                        <div class="no-print" style="display: flex; gap: 20px; margin-bottom: 20px;">
                            <div style="flex: 1; padding: 20px; background-color: #f8f9fa; border-left: 5px solid #ef4444; border-radius: 5px; box-shadow: 1px 1px 3px rgba(0,0,0,0.1);">
                                <h4 style="margin: 0; font-size: 14px; color: #000;">Risco de Adoecimento</h4>
                                <h2 style="margin: 5px 0; color: #ef4444; font-size: 28px;">{perc_ado:.2f}%</h2>
                                <p style="margin: 0; font-size: 11px; color: #333;">Critério: Média > 60 (Saúde/Burnout/Estresse/Sono)</p>
                            </div>
                            <div style="flex: 1; padding: 20px; background-color: #f8f9fa; border-left: 5px solid #eab308; border-radius: 5px; box-shadow: 1px 1px 3px rgba(0,0,0,0.1);">
                                <h4 style="margin: 0; font-size: 14px; color: #000;">Comportamentos Ofensivos</h4>
                                <h2 style="margin: 5px 0; color: #eab308; font-size: 28px;">{perc_ofe:.2f}%</h2>
                                <p style="margin: 0; font-size: 11px; color: #333;">Qualquer relato de assédio ou bullyng</p>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        df_macro = df_s.groupby('Dimensao')['Score'].mean().round(2).reset_index()
                        st.markdown("<h3 style='color: black;'>Detalhamento por Fator de Risco</h3>", unsafe_allow_html=True)
                        df_table = df_macro.rename(columns={'Dimensao': 'FATOR DE RISCO', 'Score': 'RESULTADOS (%)'})
                        def color_risk_map(v):
                            _, color = classificar_risco(v)
                            return f'background-color: {color}; color: white; font-weight: bold; text-align: center !important;'

                        st.markdown("<style>[data-testid='stTable'] { width: 50% !important; }</style>", unsafe_allow_html=True)
                        st.table(df_table.style.format({'RESULTADOS (%)': '{:.2f}%'}).map(color_risk_map, subset=['RESULTADOS (%)']))
                        st.markdown("<div class='page-break'></div>", unsafe_allow_html=True)

                        st.markdown("""
                        <div style='display: flex; justify-content: center; gap: 20px; margin-bottom: 10px; color: black;'>
                            <div style='display: flex; align-items: center; gap: 5px;'><div style='width: 12px; height: 12px; background: #22c55e; border-radius: 2px;'></div> <span><b style='color: black;'>BAIXO</b> (0-49.99%)</span></div>
                            <div style='display: flex; align-items: center; gap: 5px;'><div style='width: 12px; height: 12px; background: #eab308; border-radius: 2px;'></div> <span><b style='color: black;'>MODERADO</b> (50-74.99%)</span></div>
                            <div style='display: flex; align-items: center; gap: 5px;'><div style='width: 12px; height: 12px; background: #ef4444; border-radius: 2px;'></div> <span><b style='color: black;'>ALTO</b> (75-100%)</span></div>
                        </div>
                        """, unsafe_allow_html=True)

                        dims = df_macro['Dimensao'].unique()[:8]
                        rows_macro = [st.columns(4), st.columns(4)]
                        for i, d_name in enumerate(dims):
                            col_idx = i % 4
                            row_idx = i // 4
                            val = df_macro[df_macro['Dimensao'] == d_name]['Score'].values[0]
                            status, cor = classificar_risco(val)
                            fig = px.pie(values=[val, max(0.01, 100-val)], hole=0.6, color_discrete_sequence=[cor, '#f0f2f6'])
                            fig.update_traces(textinfo='percent', textposition='outside', hoverinfo='none', marker=dict(line=dict(color='#000', width=0)), textfont=dict(color='black'), opacity=1)
                            fig.add_annotation(x=0.5, y=0.5, text=f"<b>{status}</b>", showarrow=False, font=dict(size=14, color=cor))
                            fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0), height=110, font=dict(color='black'), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                            rows_macro[row_idx][col_idx].plotly_chart(fig, use_container_width=True, key=f"donut_{d_name}_{sel_c_id}_{i}")
                            rows_macro[row_idx][col_idx].markdown(f"<p style='text-align: center; font-weight: bold; font-size: 14px; margin-top: -20px; color: black;'>{d_name}</p>", unsafe_allow_html=True)

                        st.markdown("<hr class='no-print'>", unsafe_allow_html=True)
                        st.markdown("<h3 style='color: black;'>Resultado da percepção do colaborador</h3>", unsafe_allow_html=True)
                        df_full = df_macro.sort_values(by='Score', ascending=False)
                        df_full['Cor'] = df_full['Score'].apply(lambda x: classificar_risco(x)[1])
                        fig_bar = px.bar(df_full, x='Dimensao', y='Score', color='Cor', color_discrete_map={c: c for c in df_full['Cor'].unique()}, text_auto='.2f')
                        fig_bar.update_layout(showlegend=False, xaxis_title="", yaxis_title="Percentual (%)", yaxis_range=[0, 105], height=400, margin=dict(t=10, b=100, l=10, r=10), font=dict(color='black'), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                        fig_bar.update_traces(textfont=dict(color='black'), textangle=0, opacity=1)
                        fig_bar.update_xaxes(tickmode='linear', tickangle=-45, tickfont=dict(color='black', size=10)) 
                        fig_bar.update_yaxes(tickfont=dict(color='black'))
                        st.plotly_chart(fig_bar, use_container_width=True, key=f"barras_exec_{sel_c_id}")

                with tab_bruto:
                    df_exp = df_raw[['Setor', 'Função', 'Dimensao', 'Enunciado', 'Resposta']].fillna("Não Informado")
                    st.dataframe(df_exp, use_container_width=True)
                    buf = io.BytesIO(); df_exp.to_excel(buf, index=False)
                    st.download_button("📥 Excel (.xlsx)", buf.getvalue(), "relatorio_bruto.xlsx", key="down_bruto_final")

def main():
    params = st.query_params
    emp_code = params.get("emp")
    if emp_code:
        db = get_db()
        empresa = db.query(Empresa).filter_by(codigo_empresa=emp_code).first()
        if empresa:
            if 'logged_user_id' not in st.session_state: login_colaborador(empresa)
            else:
                user = db.query(Funcionario).get(st.session_state['logged_user_id'])
                if user: portal_colaborador(empresa, user)
                else: st.session_state.clear(); st.rerun()
        else: st.error("Empresa não encontrada.")
    else: admin_portal()

if __name__ == "__main__":
    main()