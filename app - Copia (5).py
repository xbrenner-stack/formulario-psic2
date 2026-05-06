import streamlit as st
import pandas as pd
import re
import json
import io
from datetime import datetime, date
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, UniqueConstraint, Boolean, text
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
    nome_responsavel = Column(String(200), default="")
    registro_responsavel = Column(String(200), default="")
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

with engine.connect() as conn:
    try: 
        conn.execute(text("ALTER TABLE empresas ADD COLUMN nome_responsavel VARCHAR(200) DEFAULT ''"))
        conn.commit()
    except: pass
    try: 
        conn.execute(text("ALTER TABLE empresas ADD COLUMN registro_responsavel VARCHAR(200) DEFAULT ''"))
        conn.commit()
    except: pass

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
                    c3, c4 = st.columns(2)
                    resp_nome = c3.text_input("Responsável Técnico", help="Nome que sairá na assinatura. Ex: Abel Luiz de Oliveira")
                    resp_reg = c4.text_input("Registro Profissional", help="Ex: CRM/MG 10.419")
                    link = st.text_input("Link do Google Forms")
                    senha = st.text_input("Senha do RH", type="password")
                    
                    if st.form_submit_button("Salvar Empresa"):
                        if db.query(Empresa).filter_by(codigo_empresa=codigo).first(): st.error("Código já existe!")
                        else:
                            db.add(Empresa(codigo_empresa=codigo, nome_empresa=nome, link_forms=link, senha_rh=senha, nome_responsavel=resp_nome, registro_responsavel=resp_reg))
                            db.commit(); st.success("Empresa cadastrada!"); st.rerun()

            empresas = db.query(Empresa).order_by(Empresa.nome_empresa.asc()).all()
            df_emp = pd.DataFrame([{'id': e.id, 'Nome': e.nome_empresa, 'Código': e.codigo_empresa, 'Senha RH': e.senha_rh, 'Link': e.link_forms, 'Responsável': e.nome_responsavel, 'Registro': e.registro_responsavel} for e in empresas])
            if df_emp.empty: df_emp = pd.DataFrame(columns=['id', 'Nome', 'Código', 'Senha RH', 'Link', 'Responsável', 'Registro'])
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
                            e_db.nome_responsavel = str(row.get('Responsável', ''))
                            e_db.registro_responsavel = str(row.get('Registro', ''))
                    elif pd.notna(row.get('Nome')):
                        db.add(Empresa(nome_empresa=str(row['Nome']), codigo_empresa=str(row['Código']), senha_rh=str(row['Senha RH']), link_forms=str(row['Link']), nome_responsavel=str(row.get('Responsável', '')), registro_responsavel=str(row.get('Registro', ''))))
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
                            df_bkp = pd.DataFrame([{'Ordem': p.ordem, 'Enunciado': p.enunciado, 'Ajuda': p.texto_ajuda, 'Dimensão': p.dimensao, 'Inverter': bool(p.inverter_pontuacao), 'Tipo': p.tipo_pergunta, 'Opcoes': p.opcoes_json} for p in q.perguntas])
                            buf = io.BytesIO(); df_bkp.to_excel(buf, index=False)
                            st.download_button("📥 Exportar Backup", buf.getvalue(), f"backup_q_{q.id}.xlsx", key=f"bkp_{q.id}")
                            st.divider()
                        
                        rows_p = [{'id': p.id, 'Ordem': p.ordem, 'Enunciado': p.enunciado, 'Ajuda': p.texto_ajuda, 'Dimensão': p.dimensao, 'Inverter': bool(p.inverter_pontuacao), 'Tipo': p.tipo_pergunta, 'Opções': p.opcoes_json} for p in q.perguntas]
                        df_p = pd.DataFrame(rows_p) if rows_p else pd.DataFrame(columns=['id', 'Ordem', 'Enunciado', 'Ajuda', 'Dimensão', 'Inverter', 'Tipo', 'Opções'])
                        
                        ed_p = st.data_editor(
                            df_p.sort_values(by=['Ordem', 'id'], ignore_index=True) if not df_p.empty else df_p, 
                            key=f"ed_p_{q.id}", 
                            num_rows="dynamic", 
                            use_container_width=True, 
                            disabled=["id"], 
                            column_config={
                                "id": None, 
                                "Ordem": st.column_config.NumberColumn(step=1), 
                                "Inverter": st.column_config.CheckboxColumn("Inverter Score?"),
                                "Tipo": st.column_config.SelectboxColumn(options=["escala", "lista", "texto"])
                            }
                        )
                        
                        if st.button("💾 Salvar Perguntas", key=f"sv_p_{q.id}"):
                            ids_b = {p.id for p in q.perguntas}; ids_t = set(pd.to_numeric(ed_p['id'], errors='coerce').dropna().astype(int))
                            for id_d in (ids_b - ids_t):
                                p_d = db.query(Pergunta).get(id_d)
                                if p_d: db.delete(p_d)
                            for _, r in ed_p.iterrows():
                                inv_val = 1 if r.get('Inverter') else 0
                                if pd.notna(r.get('id')):
                                    p_db = db.query(Pergunta).get(int(r['id']))
                                    if p_db: 
                                        p_db.ordem = int(r.get('Ordem', 0))
                                        p_db.enunciado = str(r['Enunciado'])
                                        p_db.texto_ajuda = str(r.get('Ajuda', ''))
                                        p_db.dimensao = str(r.get('Dimensão', ''))
                                        p_db.inverter_pontuacao = inv_val
                                        p_db.tipo_pergunta = str(r.get('Tipo', 'escala'))
                                        p_db.opcoes_json = str(r.get('Opções', '{}'))
                                elif pd.notna(r.get('Enunciado')):
                                    db.add(Pergunta(questionario_id=q.id, ordem=int(r.get('Ordem', 0)), enunciado=str(r['Enunciado']), texto_ajuda=str(r.get('Ajuda', '')), dimensao=str(r.get('Dimensão', '')), inverter_pontuacao=inv_val, tipo_pergunta=str(r.get('Tipo', 'escala')), opcoes_json=str(r.get('Opções', '{"1":"Nunca","2":"Sempre"}'))))
                            db.commit(); st.success("Salvo!"); st.rerun()

                        st.divider(); tab_m, tab_l = st.tabs(["✍️ Manual", "📥 Em Lote"])
                        with tab_m:
                            with st.form(f"fm_p_{q.id}"):
                                o, en, aj, di = st.number_input("Ordem", min_value=0), st.text_input("Enunciado"), st.text_input("Ajuda"), st.text_input("Dimensão")
                                inv_form = st.checkbox("Inverter Pontuação (Marque para inverter as notas da escala)")
                                ti = st.selectbox("Tipo", ["Escala (Bolinhas)", "Lista Suspensa", "Texto Livre"])
                                op = st.text_area("Opções (JSON)", value='{"1": "Nunca", "2": "Sempre"}')
                                if st.form_submit_button("Adicionar"):
                                    t_m = {"Escala (Bolinhas)": "escala", "Lista Suspensa": "lista", "Texto Livre": "texto"}
                                    db.add(Pergunta(questionario_id=q.id, ordem=o, enunciado=en, texto_ajuda=aj, dimensao=di, inverter_pontuacao=1 if inv_form else 0, tipo_pergunta=t_m[ti], opcoes_json=op))
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

                query_respostas_base = db.query(Funcionario.setor, Funcionario.funcao, Pergunta.dimensao, Pergunta.enunciado, Pergunta.inverter_pontuacao, Answer.resposta_texto, Funcionario.cpf, Funcionario.id, Pergunta.opcoes_json, Pergunta.ordem)\
                    .join(SurveySession, Answer.session_id == SurveySession.id)\
                    .join(Funcionario, SurveySession.funcionario_id == Funcionario.id)\
                    .join(Pergunta, Answer.pergunta_id == Pergunta.id)\
                    .filter(SurveySession.campanha_id == sel_c_id)
                    
                res_base = query_respostas_base.all()
                colunas_df = ['Setor', 'Função', 'Dimensao', 'Enunciado', 'Inverter', 'Resposta', 'CPF', 'FuncID', 'OpcoesJSON', 'Ordem']
                df_global = pd.DataFrame(res_base, columns=colunas_df) if res_base else pd.DataFrame(columns=colunas_df)

                is_sim_mode = st.session_state.get(f"sim_toggle_{sel_c_id}", False)
                if is_sim_mode and f'sim_data_{sel_c_id}' in st.session_state:
                    sim_df = st.session_state[f'sim_data_{sel_c_id}']
                    if len(sim_df) == len(df_global):
                        df_global['Resposta'] = sim_df['Resposta'].values
                        df_global['Setor'] = sim_df['Setor'].values
                        df_global['Função'] = sim_df['Função'].values
                
                st.markdown("<br>", unsafe_allow_html=True)
                lista_setores_disponiveis = [s for s in df_global['Setor'].dropna().unique() if str(s).strip() != ""]
                lista_setores_disponiveis.sort()
                
                st.markdown("<div class='no-print'>", unsafe_allow_html=True)
                setores_selecionados = st.multiselect(
                    "🔍 Filtro de Escopo (Deixe em branco para Visão Global da Empresa)", 
                    options=lista_setores_disponiveis,
                    help="Selecione um ou mais setores para gerar laudos específicos. Deixe vazio para ver o resultado da empresa inteira."
                )
                st.markdown("</div>", unsafe_allow_html=True)
                
                if not setores_selecionados:
                    txt_escopo_avaliado = "Global (Todos os Setores)"
                    df_b = df_global.copy()
                elif len(setores_selecionados) == 1:
                    txt_escopo_avaliado = f"Setor: {setores_selecionados[0]}"
                    df_b = df_global[df_global['Setor'].isin(setores_selecionados)].copy()
                else:
                    txt_escopo_avaliado = f"Setores Agrupados ({', '.join(setores_selecionados)})"
                    df_b = df_global[df_global['Setor'].isin(setores_selecionados)].copy()
                
                df_raw = df_b.copy()

                if not df_b.empty:
                    df_b['Resposta'] = pd.to_numeric(df_b['Resposta'], errors='coerce')
                    def calc_score(r, inv):
                        if pd.isna(r) or r < 1 or r > 5: return None
                        if inv == 1: return {1:100, 2:75, 3:50, 4:25, 5:0}.get(r)
                        return {1:0, 2:25, 3:50, 4:75, 5:100}.get(r)
                        
                    df_b['Score'] = df_b.apply(lambda x: calc_score(x['Resposta'], x['Inverter']), axis=1)
                    df_s = df_b.dropna(subset=['Score'])
                
                if is_sim_mode:
                    st.warning("🔬 **MODO SIMULAÇÃO ATIVO:** Os gráficos e relatórios abaixo refletem os dados alterados na aba 'Dados Brutos'. Desligue a chave na aba para retornar aos dados reais do banco.")

                tab_capa, tab_exec, tab_classif, tab_estat, tab_metodo, tab_bruto, tab_ger = st.tabs([
                    "📑 Capa e Encerramento", "📊 Dashboard Gráfico", "📋 Relatório Classificatório", 
                    "📈 Estatísticas", "📖 Metodologia", "📥 Dados Brutos", "⚙️ Gerenciar"
                ])
                
                with tab_ger:
                    c1, c2 = st.columns(2)
                    c1.write(f"**Status: {c_obj.status}**")
                    if c_obj.status == "Ativa" and st.button("🔴 Encerrar Campanha"):
                        c_obj.status = "Encerrada"; db.commit(); st.rerun()
                    if st.button("🗑️ Excluir Campanha"):
                        db.delete(c_obj); db.commit(); st.rerun()

                    st.divider()
                    st.markdown("### 📥 Importação e Exportação de Respostas (Planilha)")
                    st.write("Use esta ferramenta para subir respostas preenchidas no papel ou em sistemas externos. Não é necessário CPF: o sistema criará respondentes anônimos para cada linha importada.")
                    
                    perguntas_campanha = db.query(Pergunta).filter_by(questionario_id=c_obj.questionario_id).order_by(Pergunta.ordem.asc(), Pergunta.id.asc()).all()
                    
                    if perguntas_campanha:
                        colunas_matriz = ['Identificador (Opcional)', 'Setor', 'Função'] + [f"Q{p.ordem:02d} - {p.enunciado}" for p in perguntas_campanha]
                        df_modelo = pd.DataFrame(columns=colunas_matriz)
                        for i in range(3): df_modelo.loc[i] = [""] * len(colunas_matriz)
                        
                        buf_mod = io.BytesIO()
                        df_modelo.to_excel(buf_mod, index=False)
                        
                        col_bt1, col_bt2 = st.columns(2)
                        col_bt1.download_button("🔽 1. Baixar Planilha Modelo (Vazia)", buf_mod.getvalue(), f"modelo_importacao_{c_obj.id}.xlsx", help="Planilha com os cabeçalhos corretos para importação (Sem CPF).")
                        
                        todas_sessoes = db.query(SurveySession).filter_by(campanha_id=c_obj.id).all()
                        if todas_sessoes:
                            linhas_export = []
                            for sessao in todas_sessoes:
                                linha = {
                                    "Identificador (Opcional)": sessao.funcionario.nome,
                                    "Setor": sessao.funcionario.setor,
                                    "Função": sessao.funcionario.funcao
                                }
                                for resp in sessao.respostas:
                                    p = db.query(Pergunta).get(resp.pergunta_id)
                                    if p:
                                        linha[f"Q{p.ordem:02d} - {p.enunciado}"] = resp.resposta_texto
                                linhas_export.append(linha)
                            
                            df_export = pd.DataFrame(linhas_export)
                            for c in colunas_matriz:
                                if c not in df_export.columns: df_export[c] = ""
                            df_export = df_export[colunas_matriz]
                            
                            buf_exp = io.BytesIO()
                            df_export.to_excel(buf_exp, index=False)
                            col_bt2.download_button("📤 Exportar Respostas Atuais (Matriz)", buf_exp.getvalue(), f"respostas_matriz_{c_obj.id}.xlsx", help="Exporta as respostas atuais no mesmo formato da planilha modelo.")

                        st.write("---")
                        st.write("🔼 **2. Fazer Upload da Planilha Preenchida**")
                        up_respostas = st.file_uploader("Upload Planilha (.xlsx)", type=['xlsx'], key=f"up_resp_anon_{c_obj.id}")
                        
                        if up_respostas:
                            df_up_resp = pd.read_excel(up_respostas)
                            if st.button("Confirmar Importação de Respostas", type="primary"):
                                sucesso_count = 0
                                cols_perguntas = [c for c in df_up_resp.columns if str(c).startswith('Q') and ' - ' in str(c)]
                                
                                map_col_to_id = {}
                                for c in cols_perguntas:
                                    try:
                                        ordem_str = str(c).split(' - ')[0].replace('Q', '')
                                        ordem_num = int(ordem_str)
                                        p_banco = next((p for p in perguntas_campanha if p.ordem == ordem_num), None)
                                        if p_banco:
                                            map_col_to_id[c] = p_banco.id
                                    except:
                                        pass

                                for index, row in df_up_resp.iterrows():
                                    tem_resposta = False
                                    for c in cols_perguntas:
                                        if pd.notna(row.get(c)) and str(row.get(c)).strip() != "":
                                            tem_resposta = True
                                            break
                                            
                                    if not tem_resposta:
                                        continue
                                        
                                    identificador = str(row.get('Identificador (Opcional)', f"Anônimo {index+1}"))
                                    if identificador == "nan" or identificador.strip() == "":
                                        identificador = f"Anônimo {index+1}"
                                        
                                    setor_val = str(row.get('Setor', 'Não Informado'))
                                    if setor_val == "nan" or setor_val.strip() == "": setor_val = "Não Informado"
                                    
                                    funcao_val = str(row.get('Função', 'Não Informado'))
                                    if funcao_val == "nan" or funcao_val.strip() == "": funcao_val = "Não Informado"
                                        
                                    cpf_fake = f"ANON{int(time.time()*1000)}{index}"
                                    
                                    func_anonimo = Funcionario(
                                        empresa_id=c_obj.empresa_id,
                                        cpf=cpf_fake,
                                        nome=identificador,
                                        data_nasc="01/01/1900",
                                        setor=setor_val,
                                        funcao=funcao_val,
                                        status="Concluído",
                                        ativo=True
                                    )
                                    db.add(func_anonimo)
                                    db.flush() 
                                    
                                    nova_sessao = SurveySession(funcionario_id=func_anonimo.id, campanha_id=c_obj.id)
                                    db.add(nova_sessao)
                                    db.flush()
                                    
                                    for col in cols_perguntas:
                                        val = row.get(col)
                                        if pd.notna(val) and str(val).strip() != "":
                                            p_id = map_col_to_id.get(col)
                                            if p_id:
                                                db.add(Answer(session_id=nova_sessao.id, pergunta_id=p_id, resposta_texto=str(val).strip()))
                                                
                                    sucesso_count += 1
                                    
                                db.commit()
                                if sucesso_count > 0:
                                    st.success(f"✅ Sucesso! {sucesso_count} respostas anônimas foram importadas e adicionadas aos resultados.")
                                    time.sleep(3)
                                    st.rerun()
                                else:
                                    st.warning("Nenhuma resposta válida encontrada na planilha para importar.")

                if df_b.empty: 
                    st.warning("Aguardando primeiras respostas...")
                else:
                    with tab_capa:
                        st.markdown("""
                        <style>
                        @media print {
                            @page { size: A4 portrait !important; margin: 15mm !important; }
                            body { zoom: 1.0 !important; color: black !important; }
                            header, footer, [data-testid="stSidebar"], [data-testid="stHeader"], .stButton { display: none !important; }
                            h1, [data-testid="stExpander"], [data-testid="stSelectbox"], div[data-baseweb="tab-list"], .no-print { display: none !important; }
                            .appview-container, .stApp, .main, .block-container { max-width: 100% !important; padding-top: 0 !important; margin-top: 0 !important; padding-bottom: 0 !important;}
                            * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color: black !important; }
                        }
                        </style>
                        """, unsafe_allow_html=True)
                        
                        if st.button("🖨️ Imprimir Capa e Encerramento"):
                            script = f"<script>window.parent.print();</script><div style='display:none;'>{time.time()}</div>"
                            st.components.v1.html(script, height=0)
                            
                        nome_responsavel = c_obj.empresa.nome_responsavel if c_obj.empresa.nome_responsavel else "Nome do Responsável Técnico"
                        registro_responsavel = c_obj.empresa.registro_responsavel if c_obj.empresa.registro_responsavel else "Registro Profissional"
                        
                        st.markdown(f"""
                        <!-- CAPA DO RELATÓRIO -->
                        <div style="text-align: center; font-family: sans-serif; border: 1px solid #ccc; padding: 40px; border-radius: 5px;">
                            <br><br><br><br>
                            <h1 style="color: #1560bd; font-size: 28px;">RELATÓRIO DIAGNÓSTICO DE RISCOS PSICOSSOCIAIS</h1>
                            <h2 style="color: #333; font-size: 18px;">Diretrizes para o Programa de Gerenciamento de Riscos (PGR)</h2>
                            <br><br><br><br><br>
                            <h3 style="color: #000;">Empresa Avaliada:</h3>
                            <p style="font-size: 22px; font-weight: bold;">{contexto}</p>
                            <br><br>
                            <h3 style="color: #000;">Identificação da Campanha:</h3>
                            <p style="font-size: 18px;">{c_obj.nome_campanha}</p>
                            <br><br><br><br><br><br><br>
                            <p style="font-size: 14px; color: #666;">Data de Emissão: {datetime.now().strftime('%d/%m/%Y')}</p>
                        </div>
                        
                        <div style='page-break-before: always;'></div>
                        <br><br>
                        
                        <!-- TERMO DE ENCERRAMENTO -->
                        <div style="text-align: center; font-family: sans-serif; border: 1px solid #ccc; padding: 40px; border-radius: 5px;">
                            <br><br>
                            <h2 style="color: #000; text-decoration: underline;">PARECER TÉCNICO E DIRETRIZES DE SST</h2>
                            <br><br>
                            <p style="text-align: justify; font-size: 14px; line-height: 1.6;">
                            O presente relatório técnico apresenta e consolida os resultados do diagnóstico de riscos psicossociais realizado na empresa <b>{contexto}</b>, obtidos por meio da aplicação do inventário estruturado COPSOQ-II Versão Média.
                            <br><br>
                            O levantamento seguiu rigorosos critérios metodológicos, estatísticos e de sigilo. Os dados aqui expostos fornecem os subsídios técnicos necessários para a etapa de identificação de perigos e avaliação de riscos do Programa de Gerenciamento de Riscos (PGR), em conformidade com a NR-01. As medidas preventivas sugeridas devem ser validadas, priorizadas e integradas ao plano de ação da organização sob a coordenação do Serviço Especializado em Engenharia de Segurança e em Medicina do Trabalho (SESMT) ou responsável de SST.
                            </p>
                            <br><br><br><br><br>
                            <p>____________________________________________________________________</p>
                            <p style="margin: 0; font-weight: bold; font-size: 18px; color: #000;">{nome_responsavel}</p>
                            <p style="margin: 0; font-size: 14px; color: #333;">{registro_responsavel}</p>
                            <br><br>
                            <p style="font-size: 12px; color: #666;">Documento gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                        </div>
                        """, unsafe_allow_html=True)

                    with tab_classif:
                        st.markdown("""
                        <style>
                        @media print {
                            @page { size: A4 portrait !important; margin: 10mm !important; }
                            body { zoom: 0.85 !important; }
                            header, footer, [data-testid="stSidebar"], [data-testid="stHeader"], .stButton { display: none !important; }
                            h1, [data-testid="stExpander"], [data-testid="stSelectbox"], div[data-baseweb="tab-list"], .no-print { display: none !important; }
                            .appview-container, .stApp, .main, .block-container { max-width: 100% !important; padding-top: 0 !important; margin-top: 0 !important; padding-bottom: 0 !important;}
                            div[data-testid="stVerticalBlock"] > div:first-child { padding-top: 0 !important; }
                            * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
                        }
                        </style>
                        """, unsafe_allow_html=True)

                        if st.button("🖨️ Imprimir Relatório Classificatório"):
                            script = f"<script>window.parent.print();</script><div style='display:none;'>{time.time()}</div>"
                            st.components.v1.html(script, height=0)

                        DICT_FATORES = {
                            "Exigências quantitativas": {"macro": "EL", "macro_nome": "EXIGÊNCIAS LABORAIS - EL", "acao": "Reorganizar tarefas e redistribuir carga de trabalho entre a equipe."},
                            "Ritmo de trabalho acelerado": {"macro": "EL", "macro_nome": "EXIGÊNCIAS LABORAIS - EL", "acao": "Rever prazos e fluxos operacionais; incluir pausas programadas."},
                            "Ritmo de trabalho": {"macro": "EL", "macro_nome": "EXIGÊNCIAS LABORAIS - EL", "acao": "Rever prazos e fluxos operacionais; incluir pausas programadas."},
                            "Altas exigências cognitivas": {"macro": "EL", "macro_nome": "EXIGÊNCIAS LABORAIS - EL", "acao": "Fornecer suporte técnico, treinamentos e ferramentas que facilitem decisões."},
                            "Exigências cognitivas": {"macro": "EL", "macro_nome": "EXIGÊNCIAS LABORAIS - EL", "acao": "Fornecer suporte técnico, treinamentos e ferramentas que facilitem decisões."},
                            "Altas exigências emocionais": {"macro": "EL", "macro_nome": "EXIGÊNCIAS LABORAIS - EL", "acao": "Criar espaços de escuta ativa e oferecer suporte psicológico contínuo."},
                            "Exigências emocionais": {"macro": "EL", "macro_nome": "EXIGÊNCIAS LABORAIS - EL", "acao": "Criar espaços de escuta ativa e oferecer suporte psicológico contínuo."},
                            "Pouca influência no trabalho": {"macro": "OTC", "macro_nome": "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC", "acao": "Ampliar a participação dos colaboradores em decisões sobre suas atividades."},
                            "Influência no trabalho": {"macro": "OTC", "macro_nome": "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC", "acao": "Ampliar a participação dos colaboradores em decisões sobre suas atividades."},
                            "Baixa possibilidades de desenvolvimento": {"macro": "OTC", "macro_nome": "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC", "acao": "Estabelecer plano de carreira e treinamentos periódicos."},
                            "Possibilidades de desenvolvimento": {"macro": "OTC", "macro_nome": "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC", "acao": "Estabelecer plano de carreira e treinamentos periódicos."},
                            "Pouca previsibilidade de rotina": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Garantir maior clareza na agenda de tarefas e planejamento de demandas."},
                            "Previsibilidade": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Garantir maior clareza na agenda de tarefas e planejamento de demandas."},
                            "Pouca transparência do papel laboral desempenhado": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Atualizar e comunicar com clareza as descrições de cargos e responsabilidades."},
                            "Transparência do papel laboral desempenhado": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Atualizar e comunicar com clareza as descrições de cargos e responsabilidades."},
                            "Déficit nas recompensas": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Implementar sistema de reconhecimento por desempenho (não apenas financeiro)."},
                            "Recompensas": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Implementar sistema de reconhecimento por desempenho (não apenas financeiro)."},
                            "Conflitos laborais": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Criar um comitê de mediação de conflitos e promover treinamentos em comunicação."},
                            "Pouco apoio social de colegas": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Promover integração por meio de dinâmicas de grupo e projetos colaborativos."},
                            "Apoio social de colegas": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Promover integração por meio de dinâmicas de grupo e projetos colaborativos."},
                            "Pouco apoio social dos superiores": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Capacitar líderes em gestão humanizada e empática."},
                            "Apoio social de superiores": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Capacitar líderes em gestão humanizada e empática."},
                            "Pouca cooperação no trabalho": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Estimular o trabalho em equipe com metas compartilhadas."},
                            "Comunidade social no trabalho": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Estimular o trabalho em equipe com metas compartilhadas."},
                            "Má qualidade da liderança": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Realizar avaliação dos líderes com feedback 360° e programa de desenvolvimento de líderes."},
                            "Qualidade de liderança": {"macro": "RSL", "macro_nome": "RELAÇÕES SOCIAIS E LIDERANÇA - RSL", "acao": "Realizar avaliação dos líderes com feedback 360° e programa de desenvolvimento de líderes."},
                            "Baixa confiança entre pares": {"macro": "VLT", "macro_nome": "VALORES NO LOCAL DE TRABALHO - VLT", "acao": "Estimular valores como ética e respeito; aplicar códigos de conduta."},
                            "Confiança horizontal": {"macro": "VLT", "macro_nome": "VALORES NO LOCAL DE TRABALHO - VLT", "acao": "Estimular valores como ética e respeito; aplicar códigos de conduta."},
                            "Baixa confiança na gerência": {"macro": "VLT", "macro_nome": "VALORES NO LOCAL DE TRABALHO - VLT", "acao": "Aumentar a transparência das decisões da gestão e comunicar-se melhor com a equipe."},
                            "Confiança vertical": {"macro": "VLT", "macro_nome": "VALORES NO LOCAL DE TRABALHO - VLT", "acao": "Aumentar a transparência das decisões da gestão e comunicar-se melhor com a equipe."},
                            "Injustiça e desrespeito": {"macro": "VLT", "macro_nome": "VALORES NO LOCAL DE TRABALHO - VLT", "acao": "Criar políticas organizacionais claras de justiça e respeito no ambiente de trabalho."},
                            "Justiça e respeito": {"macro": "VLT", "macro_nome": "VALORES NO LOCAL DE TRABALHO - VLT", "acao": "Criar políticas organizacionais claras de justiça e respeito no ambiente de trabalho."},
                            "Baixa autoeficácia": {"macro": "P", "macro_nome": "PERSONALIDADE - P", "acao": "Oferecer feedbacks positivos e oportunidades de desenvolvimento individual."},
                            "Auto-eficácia": {"macro": "P", "macro_nome": "PERSONALIDADE - P", "acao": "Oferecer feedbacks positivos e oportunidades de desenvolvimento individual."},
                            "Trabalho sem significado": {"macro": "OTC", "macro_nome": "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC", "acao": "Realinhar as tarefas ao propósito organizacional e envolver os colaboradores na missão."},
                            "Significado do trabalho": {"macro": "OTC", "macro_nome": "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC", "acao": "Realinhar as tarefas ao propósito organizacional e envolver os colaboradores na missão."},
                            "Pouco compromisso face ao local de trabalho": {"macro": "OTC", "macro_nome": "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC", "acao": "Fortalecer o vínculo organizacional com ações de valorização e pertencimento."},
                            "Compromisso face ao local de trabalho": {"macro": "OTC", "macro_nome": "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC", "acao": "Fortalecer o vínculo organizacional com ações de valorização e pertencimento."},
                            "Insatisfação no trabalho": {"macro": "ITI", "macro_nome": "INTERFACE TRABALHO-INDIVÍDUO - ITI", "acao": "Aplicar pesquisas de clima e agir sobre os pontos críticos com agilidade."},
                            "Satisfação no trabalho": {"macro": "ITI", "macro_nome": "INTERFACE TRABALHO-INDIVÍDUO - ITI", "acao": "Aplicar pesquisas de clima e agir sobre os pontos críticos com agilidade."},
                            "Insegurança laboral": {"macro": "ITI", "macro_nome": "INTERFACE TRABALHO-INDIVÍDUO - ITI", "acao": "Garantir estabilidade por meio de contratos claros e comunicação sobre o futuro."},
                            "Falta de saúde geral": {"macro": "SBE", "macro_nome": "SAÚDE E BEM-ESTAR - SBE", "acao": "Criar programas de saúde física, mental e preventiva com incentivos à adesão."},
                            "Saúde Geral": {"macro": "SBE", "macro_nome": "SAÚDE E BEM-ESTAR - SBE", "acao": "Criar programas de saúde física, mental e preventiva com incentivos à adesão."},
                            "Conflito trabalho/ família": {"macro": "ITI", "macro_nome": "INTERFACE TRABALHO-INDIVÍDUO - ITI", "acao": "Adotar políticas de flexibilidade, como horários adaptáveis ou home office parcial."},
                            "Conflito trabalho/família": {"macro": "ITI", "macro_nome": "INTERFACE TRABALHO-INDIVÍDUO - ITI", "acao": "Adotar políticas de flexibilidade, como horários adaptáveis ou home office parcial."},
                            "Problemas em dormir": {"macro": "SBE", "macro_nome": "SAÚDE E BEM-ESTAR - SBE", "acao": "Promover campanhas de higiene do sono e equilíbrio jornada/descanso."},
                            "Burnout": {"macro": "SBE", "macro_nome": "SAÚDE E BEM-ESTAR - SBE", "acao": "Reduzir carga de trabalho, flexibilizar horários e investir em suporte emocional."},
                            "Estresse": {"macro": "SBE", "macro_nome": "SAÚDE E BEM-ESTAR - SBE", "acao": "Implantar programas de gestão do estresse, estratégias de copyng, inteligência emocional (mindfulness, ginástica laboral)."},
                            "Stress": {"macro": "SBE", "macro_nome": "SAÚDE E BEM-ESTAR - SBE", "acao": "Implantar programas de gestão do estresse, estratégias de copyng, inteligência emocional (mindfulness, ginástica laboral)."},
                            "Sintomas depressivos": {"macro": "SBE", "macro_nome": "SAÚDE E BEM-ESTAR - SBE", "acao": "Disponibilizar atendimento psicológico e acompanhar com RH e SESMT."},
                            "Comportamentos ofensivos": {"macro": "CO", "macro_nome": "COMPORTAMENTOS OFENSIVOS - CO", "acao": "Criar canais de denúncia seguros e implementar políticas de tolerância zero para assédio."}
                        }

                        OBS_MACRO = {
                            "EXIGÊNCIAS LABORAIS - EL": {
                                "FAVORÁVEL": "Carga de trabalho adequada e ritmo equilibrado.",
                                "MODERADO": "Carga de trabalho no limite; necessário monitorar e balancear.",
                                "RISCO": "Sobrecarga de trabalho identificada, necessidade de revisão imediata."
                            },
                            "ORGANIZAÇÃO DO TRABALHO E CONTEÚDO - OTC": {
                                "FAVORÁVEL": "Boa autonomia e uso de habilidades no trabalho.",
                                "MODERADO": "Autonomia parcial; oportunidades para maior engajamento.",
                                "RISCO": "Pouco controle sobre tarefas e decisões; desmotivação latente."
                            },
                            "RELAÇÕES SOCIAIS E LIDERANÇA - RSL": {
                                "FAVORÁVEL": "Boa comunicação, papéis claros e suporte da liderança.",
                                "MODERADO": "Algumas falhas de comunicação e clareza de papéis.",
                                "RISCO": "Conflitos interpessoais ou lacunas significativas na liderança."
                            },
                            "INTERFACE TRABALHO-INDIVÍDUO - ITI": {
                                "FAVORÁVEL": "Bom equilíbrio entre vida pessoal e profissional.",
                                "MODERADO": "Algumas interferências entre trabalho e vida pessoal.",
                                "RISCO": "Forte desequilíbrio, trabalho afetando negativamente a vida pessoal."
                            },
                            "VALORES NO LOCAL DE TRABALHO - VLT": {
                                "FAVORÁVEL": "Ambiente de respeito, ética e confiança.",
                                "MODERADO": "Confiabilidade razoável, com pequenas tensões percebidas.",
                                "RISCO": "Falta de confiança, desrespeito ou percepção de injustiça."
                            },
                            "PERSONALIDADE - P": {
                                "FAVORÁVEL": "Alta autoeficácia e perspectivas positivas.",
                                "MODERADO": "Autoeficácia moderada; espaço para fortalecimento individual.",
                                "RISCO": "Baixa autoeficácia e insegurança; necessidade de suporte."
                            },
                            "SAÚDE E BEM-ESTAR - SBE": {
                                "FAVORÁVEL": "Bem-estar físico e emocional preservados; sono adequado.",
                                "MODERADO": "Sinais leves de fadiga, estresse ou sono irregular.",
                                "RISCO": "Presença de exaustão, estresse alto ou sintomas de adoecimento."
                            },
                            "COMPORTAMENTOS OFENSIVOS - CO": {
                                "FAVORÁVEL": "Ambiente respeitoso, sem relatos de ofensas.",
                                "MODERADO": "Ocorrências pontuais de desrespeito ou conflitos.",
                                "RISCO": "Relatos críticos de assédio ou violência; tolerância zero."
                            }
                        }

                        def classificar_risco_novo(v):
                            if pd.isna(v): return 'N/A', 'Monitorar'
                            if v <= 49.99: return 'FAVORÁVEL', 'Monitorar'
                            if v <= 74.99: return 'MODERADO', 'Planejar ações corretivas'
                            return 'RISCO', 'Intervenção imediata'

                        def build_html_table(df, headers, widths):
                            html = "<table style='width: 100%; border-collapse: collapse; margin-bottom: 10px; color: black; font-size: 9px; page-break-inside: avoid;'>"
                            html += "<thead style='display: table-header-group;'><tr style='background-color: #1560bd; color: white;'>"
                            for i, h in enumerate(headers):
                                align = "center" if h in ['RESULTADO', 'MÉDIA', 'CLASSIFIC', 'CLASSIFICAÇÃO'] else "left"
                                html += f"<th style='padding: 4px; border: 1px solid #ddd; width: {widths[i]}; text-align: {align};'>{h}</th>"
                            html += "</tr></thead><tbody>"
                            for _, row in df.iterrows():
                                html += "<tr>"
                                for i, col in enumerate(df.columns):
                                    val = row[col]
                                    if col in ['RESULTADO', 'MÉDIA']: val = f"{val:.1f}%"
                                    
                                    align = "center" if headers[i] in ['RESULTADO', 'MÉDIA', 'CLASSIFIC', 'CLASSIFICAÇÃO'] else "left"
                                    style = f"padding: 4px; border: 1px solid #ddd; text-align: {align};"
                                    
                                    if col in ['CLASSIFIC', 'CLASSIFICAÇÃO']:
                                        if val == 'FAVORÁVEL': style += " color: #16a34a; font-weight: bold;"
                                        elif val == 'MODERADO': style += " color: #ca8a04; font-weight: bold;"
                                        elif val == 'RISCO': style += " color: #dc2626; font-weight: bold;"
                                    html += f"<td style='{style}'>{val}</td>"
                                html += "</tr>"
                            html += "</tbody></table>"
                            return html

                        fatores_scores = df_s.groupby('Dimensao')['Score'].mean().reset_index()
                        tabela1_data = []
                        for _, row in fatores_scores.iterrows():
                            dim = row['Dimensao']
                            val = row['Score']
                            info = DICT_FATORES.get(dim, {"macro": "N/A", "macro_nome": dim, "acao": "Analisar resultados e adaptar ações."})
                            nome_fator = f"{dim} - {info['macro']}" if info['macro'] != "N/A" else dim
                            status, rec = classificar_risco_novo(val)
                            
                            tabela1_data.append({
                                "FATOR DE RISCO": nome_fator,
                                "RESULTADO": val,
                                "CLASSIFIC": status,
                                "AÇÃO SUGERIDA": info['acao'],
                                "macro_nome": info['macro_nome']
                            })
                        
                        df_tabela1 = pd.DataFrame(tabela1_data)
                        df_tabela1_print = df_tabela1.drop(columns=['macro_nome']) if not df_tabela1.empty else pd.DataFrame()

                        df_macro_classif = df_tabela1.groupby('macro_nome')['RESULTADO'].mean().reset_index() if not df_tabela1.empty else pd.DataFrame(columns=['macro_nome', 'RESULTADO'])
                        tabela2_data = []
                        for _, row in df_macro_classif.iterrows():
                            mn = row['macro_nome']
                            val = row['RESULTADO']
                            status, rec = classificar_risco_novo(val)
                            obs = OBS_MACRO.get(mn, {}).get(status, "-")
                            
                            tabela2_data.append({
                                "RESULTADO - DIMENSÕES COPSOQ-II": mn,
                                "MÉDIA": val,
                                "CLASSIFICAÇÃO": status,
                                "RECOMENDAÇÕES": rec,
                                "OBSERVAÇÃO": obs
                            })
                        
                        df_tabela2 = pd.DataFrame(tabela2_data)
                        df_tabela2_print = df_tabela2.drop(columns=['OBSERVAÇÃO']) if not df_tabela2.empty else pd.DataFrame()

                        n_fav = len(df_tabela2[df_tabela2['CLASSIFICAÇÃO'] == 'FAVORÁVEL']) if not df_tabela2.empty else 0
                        n_mod = len(df_tabela2[df_tabela2['CLASSIFICAÇÃO'] == 'MODERADO']) if not df_tabela2.empty else 0
                        n_ris = len(df_tabela2[df_tabela2['CLASSIFICAÇÃO'] == 'RISCO']) if not df_tabela2.empty else 0

                        if n_ris > 0: max_risk = "RISCO"
                        elif n_mod > 0: max_risk = "MODERADO"
                        elif n_fav > 0: max_risk = "FAVORÁVEL"
                        else: max_risk = "N/A"

                        txt_conclusao = f"<p style='font-size: 12px; color: black;'><b>Nível máximo de risco identificado:</b> {max_risk}<br>"
                        txt_conclusao += f"<b>Distribuição geral:</b> {n_fav} Favorável, {n_mod} Moderado, {n_ris} Risco.</p>"

                        if max_risk == 'RISCO': 
                            txt_conclusao += "<p style='font-size: 12px; color: black;'>Há presença de riscos psicossociais significativos que podem impactar a saúde emocional e o desempenho.</p>"
                        elif max_risk == 'MODERADO': 
                            txt_conclusao += "<p style='font-size: 12px; color: black;'>Existem fatores de atenção que requerem ações preventivas para não evoluírem para quadros críticos.</p>"
                        else: 
                            txt_conclusao += "<p style='font-size: 12px; color: black;'>O ambiente de trabalho apresenta baixos riscos psicossociais e bom equilíbrio organizacional.</p>"

                        if n_mod > 0 or n_ris > 0:
                            txt_conclusao += "<p style='font-size: 12px; color: black; margin-top: 10px;'><b>As seguintes dimensões requerem atenção:</b></p><ul style='font-size: 12px; color: black;'>"
                            for _, row in df_tabela2.iterrows():
                                if row['CLASSIFICAÇÃO'] in ['MODERADO', 'RISCO']:
                                    txt_conclusao += f"<li><b>{row['RESULTADO - DIMENSÕES COPSOQ-II']} ({row['CLASSIFICAÇÃO']}):</b> {row['OBSERVAÇÃO']}</li>"
                            txt_conclusao += "</ul>"

                        st.markdown(f"""
                        <div style='text-align: center; border-bottom: 2px solid #ccc; padding-bottom: 10px; margin-bottom: 30px;'>
                            <span style='color: black; font-size: 24px; font-weight: bold;'>Classificação Analítica dos Fatores de Risco</span><br>
                            <span style='color: black; font-size: 16px;'>Resultados do Inventário COPSOQ-II Versão Média e Proposições de Intervenção</span><br><br>
                            <span style='color: #1560bd; font-size: 18px; font-weight: bold;'>Escopo Avaliado: {txt_escopo_avaliado}</span><br>
                            <span style='color: #666; font-size: 14px;'>Campanha: {c_obj.nome_campanha} | Vigência: {c_obj.data_inicio}</span>
                        </div>
                        """, unsafe_allow_html=True)

                        if not df_tabela1_print.empty:
                            st.markdown("<h3 style='color: black; font-size: 16px;'>RESULTADOS GERAIS POR FATOR DE RISCO PSICOSSOCIAL</h3>", unsafe_allow_html=True)
                            st.markdown(build_html_table(df_tabela1_print, ['FATOR DE RISCO', 'RESULTADO', 'CLASSIFIC', 'AÇÃO SUGERIDA'], ['25%', '10%', '15%', '50%']), unsafe_allow_html=True)

                            st.markdown("<h3 style='color: black; font-size: 16px; margin-top: 20px; page-break-before: always;'>TABELA DE RESULTADOS GERAIS POR DIMENSÃO</h3>", unsafe_allow_html=True)
                            st.markdown(build_html_table(df_tabela2_print, ['RESULTADO - DIMENSÕES COPSOQ-II', 'MÉDIA', 'CLASSIFICAÇÃO', 'RECOMENDAÇÕES'], ['45%', '10%', '15%', '30%']), unsafe_allow_html=True)

                        st.markdown("""
                        <h3 style='color: black; margin-top: 30px; font-size: 16px;'>Definição de cada dimensão avaliada:</h3>
                        <p style='font-size: 12px; color: black;'>
                        <b>Exigências laborais</b> verificam a carga física e mental do trabalho, como pressão por prazos, volume de tarefas e demandas emocionais.<br>
                        <b>Organização do trabalho e conteúdo</b> analisam a clareza das tarefas, autonomia, variedade e previsibilidade no trabalho.<br>
                        <b>Relações sociais e liderança</b> medem a qualidade das relações com colegas e líderes, incluindo apoio, confiança e justiça organizacional.<br>
                        <b>Interface trabalho-indivíduo</b> avalia como o trabalho afeta a vida pessoal, incluindo equilíbrio entre vida profissional e pessoal e segurança no emprego.<br>
                        <b>Valores no local de trabalho</b> exploram o alinhamento entre os valores pessoais e os da organização, além do reconhecimento e significado do trabalho.<br>
                        <b>Personalidade</b> considera traços individuais como autoestima, otimismo e estratégias de enfrentamento do estresse.<br>
                        <b>Saúde e bem-estar</b> avaliam o impacto do trabalho na saúde física e mental, incluindo sono, exaustão e satisfação geral.<br>
                        <b>Comportamentos ofensivos</b> identificam experiências de assédio, violência, discriminação ou bullying no ambiente de trabalho.
                        </p>
                        <p style='font-size: 12px; color: black; margin-bottom: 20px;'>As ações são sugeridas com base no fator de risco, porém, devem ser adaptadas à realidade da empresa. Importante ressaltar que a percepção do colaborador precisa ser analisada juntamente com o histórico da empresa, além da existência e eficácia das medidas de controle.</p>

                        <h3 style='color: black; margin-top: 20px; font-size: 16px; page-break-before: always;'>RECOMENDAÇÕES POR NÍVEL DE AÇÃO</h3>
                        <table style='width: 100%; border-collapse: collapse; margin-bottom: 10px; color: black; font-size: 10px; page-break-inside: avoid;'>
                            <thead>
                                <tr style='background-color: #1560bd; color: white;'>
                                    <th style='padding: 4px; border: 1px solid #ddd; text-align: center;'>FAIXA (%)</th>
                                    <th style='padding: 4px; border: 1px solid #ddd; text-align: center;'>INTERPRETAÇÃO</th>
                                    <th style='padding: 4px; border: 1px solid #ddd; text-align: center;'>RISCO</th>
                                    <th style='padding: 4px; border: 1px solid #ddd; text-align: left;'>RECOMENDAÇÕES</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>0 a 49.99%</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Situação favorável</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center; color: #16a34a; font-weight: bold;'>FAVORÁVEL</td><td style='padding: 4px; border: 1px solid #ddd;'>Monitorar</td></tr>
                                <tr><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>50 a 74.99%</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Situação intermediária</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center; color: #ca8a04; font-weight: bold;'>MODERADO</td><td style='padding: 4px; border: 1px solid #ddd;'>Planejar ações corretivas</td></tr>
                                <tr><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>75 a 100%</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Situação crítica</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center; color: #dc2626; font-weight: bold;'>RISCO</td><td style='padding: 4px; border: 1px solid #ddd;'>Intervenção imediata</td></tr>
                            </tbody>
                        </table>

                        <h3 style='color: black; margin-top: 20px; font-size: 16px;'>PROPOSTA DE INTERVENÇÃO</h3>
                        <p style='font-size: 12px; color: black;'>Diante dos riscos psicossociais identificados, recomenda-se a implementação de um plano de intervenção coordenado por profissional da Psicologia do Trabalho, considerando as seguintes frentes de ação:</p>
                        <table style='width: 100%; border-collapse: collapse; margin-bottom: 10px; color: black; font-size: 10px; page-break-inside: avoid;'>
                            <thead>
                                <tr style='background-color: #1560bd; color: white;'>
                                    <th style='padding: 4px; border: 1px solid #ddd; text-align: center; width: 25%;'>AÇÃO</th>
                                    <th style='padding: 4px; border: 1px solid #ddd; text-align: left; width: 55%;'>DESCRIÇÃO</th>
                                    <th style='padding: 4px; border: 1px solid #ddd; text-align: center; width: 20%;'>CRONOGRAMA</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Acompanhamento psicológico</td><td style='padding: 4px; border: 1px solid #ddd;'>Criação de espaços de escuta, como rodas de conversa e atendimentos breves no ambiente laboral, voltados ao acolhimento.</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Mensal, por demanda</td></tr>
                                <tr><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Programas de sensibilização</td><td style='padding: 4px; border: 1px solid #ddd;'>Oficinas e palestras sobre saúde mental no trabalho, autocuidado, gestão emocional e prevenção de burnout.</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Mensal, temas adaptados</td></tr>
                                <tr><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Assessoria em gestão participativa</td><td style='padding: 4px; border: 1px solid #ddd;'>Apoio à liderança na implementação de práticas transparentes, colaborativas e justas.</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Bimestral + follow-up</td></tr>
                                <tr><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Reestruturação organizacional</td><td style='padding: 4px; border: 1px solid #ddd;'>Mediação entre trabalhadores e gestão para redimensionar tarefas e resgatar o propósito nas atividades.</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>90 dias</td></tr>
                                <tr><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>Protocolo de acompanhamento</td><td style='padding: 4px; border: 1px solid #ddd;'>Revisão periódica das condições de trabalho e escuta ativa para validação de medidas aplicadas.</td><td style='padding: 4px; border: 1px solid #ddd; text-align: center;'>60 dias</td></tr>
                            </tbody>
                        </table>
                        <p style='font-size: 12px; color: black;'>Essa abordagem integrada permite não apenas atuar sobre fatores isolados, mas reconfigurar dinâmicas psicossociais adoecedoras de forma sistêmica, com base no diálogo e no fortalecimento do coletivo.</p>
                        """, unsafe_allow_html=True)

                        st.markdown("<h3 style='color: black; margin-top: 30px; font-size: 16px; page-break-before: always;'>CONCLUSÃO</h3>", unsafe_allow_html=True)
                        st.markdown("<p style='font-size: 12px; color: black;'>Os resultados obtidos constituem um panorama amplo e consistente sobre os principais fatores de risco psicossocial no ambiente laboral avaliado. A atuação da equipe técnica é central na construção de um ambiente mais saudável, por meio de intervenções que aliam análise organizacional e promoção da saúde.</p>", unsafe_allow_html=True)
                        
                        st.markdown(txt_conclusao, unsafe_allow_html=True)

                        st.markdown("""
                        <p style='font-size: 12px; color: black; margin-top: 15px;'>Recomenda-se, como próximo passo, a classificação dos riscos psicossociais com base na metodologia da NR-1, considerando:<br>
                        - Severidade dos efeitos à saúde mental e organizacional;<br>
                        - Probabilidade de ocorrência dos fatores relatados;<br>
                        - Histórico da empresa quanto a afastamentos, denúncias, absenteísmo e rotatividade;<br>
                        - Existência e eficácia das medidas de controle atualmente adotadas.</p>
                        <p style='font-size: 12px; color: black;'>Essa análise permitirá classificar os riscos, definir o nível de prioridade das ações e integrar os riscos psicossociais de forma adequada ao Programa de Gerenciamento de Riscos (PGR).</p>
                        """, unsafe_allow_html=True)

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

                        total_participantes = df_raw['FuncID'].nunique() if not df_raw.empty else 0
                        
                        st.markdown(f"""
                        <div style='text-align: center; border-bottom: 2px solid #ccc; padding-bottom: 10px; margin-bottom: 30px;'>
                            <span style='color: black; font-size: 28px; font-weight: bold;'>Relatório Psicossocial - Estatísticas</span><br>
                            <span style='color: #1560bd; font-size: 18px; font-weight: bold;'>Escopo Avaliado: {txt_escopo_avaliado}</span><br>
                            <span style='color: #666; font-size: 16px;'>Campanha: {c_obj.nome_campanha}</span><br>
                            <span style='color: #333; font-size: 14px; font-weight: bold;'>Total de Participantes: {total_participantes}</span>
                        </div>
                        """, unsafe_allow_html=True)

                        if not df_raw.empty:
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
                                    st.markdown(f"<div style='font-size: 16px; font-weight: bold; color: black; margin-top: 15px; margin-bottom: 10px; page-break-after: avoid;'>{p['Ordem']}. {enunciado} <span style='font-size: 12px; font-weight: normal; color: #666;'>({total_resp} respostas)</span></div>", unsafe_allow_html=True)
                                    
                                    html_barras = "<div style='margin-bottom: 25px; page-break-inside: avoid;'>"
                                    chaves_ordenadas = sorted([k for k in opcoes_dict.keys() if k.isdigit()], key=int)
                                    for k in chaves_ordenadas:
                                        texto_opcao = opcoes_dict[str(k)]
                                        qtd = len(df_resp[df_resp['Resposta'].astype(str) == str(k)])
                                        perc = (qtd / total_resp * 100) if total_resp > 0 else 0
                                        
                                        html_barras += f"<div style='display: flex; align-items: center; margin-bottom: 6px;'>"
                                        html_barras += f"<div style='width: 35%; font-size: 14px; color: #333;'>{texto_opcao}</div>"
                                        html_barras += f"<div class='barra-bg' style='width: 45%; background-color: #e6e6e6; border-radius: 4px; height: 18px; margin: 0 10px; position: relative; overflow: hidden; -webkit-print-color-adjust: exact;'>"
                                        html_barras += f"<div class='barra-fill' style='background-color: #1560bd; width: {perc}%; height: 100%; border-radius: 4px; -webkit-print-color-adjust: exact;'></div>"
                                        html_barras += f"</div>"
                                        html_barras += f"<div style='width: 20%; font-size: 14px; color: black; font-weight: bold; text-align: right;'>{qtd} resp. ({perc:.1f}%)</div>"
                                        html_barras += f"</div>"
                                    
                                    html_barras += "</div>"
                                    st.markdown(html_barras, unsafe_allow_html=True)

                    with tab_exec:
                        def classificar_risco_exec(v):
                            if v <= 49.99: return 'BAIXO', '#22c55e'
                            if v <= 74.99: return 'MODERADO', '#eab308'
                            return 'ALTO', '#ef4444'

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

                        if st.button("🖨️ Imprimir Dashboard Gráfico"):
                            script = f"<script>window.parent.print();</script><div style='display:none;'>{time.time()}</div>"
                            st.components.v1.html(script, height=0)

                        st.markdown("<div style='page-break-before: always;'></div>", unsafe_allow_html=True)
                        st.markdown(f"""
                        <div style='text-align: center; border-bottom: 2px solid #ccc; padding-bottom: 10px; margin-bottom: 20px;'>
                            <span style='color: black; font-size: 32px; font-weight: bold;'>Relatório de Risco Psicossocial</span><br>
                            <span style='color: #1560bd; font-size: 20px; font-weight: bold;'>Escopo Avaliado: {txt_escopo_avaliado}</span>
                        </div>
                        """, unsafe_allow_html=True)

                        if not df_s.empty:
                            df_ado = df_s[df_s['Dimensao'].isin(['Saúde Geral', 'Burnout', 'Estresse', 'Problemas de Sono', 'Stress'])]
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

                            df_macro_exec = df_s.groupby('Dimensao')['Score'].mean().round(2).reset_index()
                            st.markdown("<h3 style='color: black;'>Detalhamento por Fator de Risco</h3>", unsafe_allow_html=True)
                            df_table_exec = df_macro_exec.rename(columns={'Dimensao': 'FATOR DE RISCO', 'Score': 'RESULTADOS (%)'})
                            
                            def color_risk_map_exec(v):
                                _, color = classificar_risco_exec(v)
                                return f'background-color: {color}; color: white; font-weight: bold; text-align: center !important;'

                            st.markdown("<style>[data-testid='stTable'] { width: 50% !important; }</style>", unsafe_allow_html=True)
                            st.table(df_table_exec.style.format({'RESULTADOS (%)': '{:.2f}%'}).map(color_risk_map_exec, subset=['RESULTADOS (%)']))
                            st.markdown("<div class='page-break'></div>", unsafe_allow_html=True)

                            st.markdown("""
                            <div style='display: flex; justify-content: center; gap: 20px; margin-bottom: 10px; color: black;'>
                                <div style='display: flex; align-items: center; gap: 5px;'><div style='width: 12px; height: 12px; background: #22c55e; border-radius: 2px;'></div> <span><b style='color: black;'>BAIXO</b> (0-49.99%)</span></div>
                                <div style='display: flex; align-items: center; gap: 5px;'><div style='width: 12px; height: 12px; background: #eab308; border-radius: 2px;'></div> <span><b style='color: black;'>MODERADO</b> (50-74.99%)</span></div>
                                <div style='display: flex; align-items: center; gap: 5px;'><div style='width: 12px; height: 12px; background: #ef4444; border-radius: 2px;'></div> <span><b style='color: black;'>ALTO</b> (75-100%)</span></div>
                            </div>
                            """, unsafe_allow_html=True)

                            dims_exec = df_macro_exec['Dimensao'].unique()[:8]
                            rows_macro_exec = [st.columns(4), st.columns(4)]
                            for i, d_name in enumerate(dims_exec):
                                col_idx = i % 4
                                row_idx = i // 4
                                val = df_macro_exec[df_macro_exec['Dimensao'] == d_name]['Score'].values[0]
                                status, cor = classificar_risco_exec(val)
                                fig = px.pie(values=[val, max(0.01, 100-val)], hole=0.6, color_discrete_sequence=[cor, '#f0f2f6'])
                                fig.update_traces(textinfo='percent', textposition='outside', hoverinfo='none', marker=dict(line=dict(color='#000', width=0)), textfont=dict(color='black'), opacity=1)
                                fig.add_annotation(x=0.5, y=0.5, text=f"<b>{status}</b>", showarrow=False, font=dict(size=14, color=cor))
                                fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0), height=110, font=dict(color='black'), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                                rows_macro_exec[row_idx][col_idx].plotly_chart(fig, use_container_width=True, key=f"donut_{d_name}_{sel_c_id}_{i}")
                                rows_macro_exec[row_idx][col_idx].markdown(f"<p style='text-align: center; font-weight: bold; font-size: 14px; margin-top: -20px; color: black;'>{d_name}</p>", unsafe_allow_html=True)

                            st.markdown("<hr class='no-print'>", unsafe_allow_html=True)
                            st.markdown("<h3 style='color: black;'>Resultado da percepção do colaborador</h3>", unsafe_allow_html=True)
                            df_full_exec = df_macro_exec.sort_values(by='Score', ascending=False)
                            df_full_exec['Cor'] = df_full_exec['Score'].apply(lambda x: classificar_risco_exec(x)[1])
                            fig_bar = px.bar(df_full_exec, x='Dimensao', y='Score', color='Cor', color_discrete_map={c: c for c in df_full_exec['Cor'].unique()}, text_auto='.2f')
                            fig_bar.update_layout(showlegend=False, xaxis_title="", yaxis_title="Percentual (%)", yaxis_range=[0, 105], height=400, margin=dict(t=10, b=100, l=10, r=10), font=dict(color='black'), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                            fig_bar.update_traces(textfont=dict(color='black'), textangle=0, opacity=1)
                            fig_bar.update_xaxes(tickmode='linear', tickangle=-45, tickfont=dict(color='black', size=10)) 
                            fig_bar.update_yaxes(tickfont=dict(color='black'))
                            st.plotly_chart(fig_bar, use_container_width=True, key=f"barras_exec_{sel_c_id}")

                with tab_metodo:
                    st.markdown("""
                    <style>
                    @media print {
                        @page { size: A4 portrait !important; margin: 15mm !important; }
                        body { zoom: 0.9 !important; color: black !important; }
                        header, footer, [data-testid="stSidebar"], [data-testid="stHeader"], .stButton { display: none !important; }
                        h1, [data-testid="stExpander"], [data-testid="stSelectbox"], div[data-baseweb="tab-list"], .no-print { display: none !important; }
                        .appview-container, .stApp, .main, .block-container { max-width: 100% !important; padding-top: 0 !important; margin-top: 0 !important; padding-bottom: 0 !important;}
                        * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color: black !important; }
                        table { font-size: 11px !important; }
                    }
                    </style>
                    """, unsafe_allow_html=True)

                    if st.button("🖨️ Imprimir Metodologia Técnica"):
                        script = f"<script>window.parent.print();</script><div style='display:none;'>{time.time()}</div>"
                        st.components.v1.html(script, height=0)

                    st.markdown(f"""
                    <div style='text-align: center; margin-bottom: 20px; line-height: 1.2;'>
                        <span style='color: black; font-size: 24px; font-weight: bold;'>METODOLOGIA DE AVALIAÇÃO DE RISCOS PSICOSSOCIAIS</span><br>
                        <span style='color: black; font-size: 18px; font-weight: bold;'>INTEGRAÇÃO AO PROGRAMA DE GERENCIAMENTO DE RISCOS (PGR)</span>
                    </div>

                    <h3 style='color: #1560bd; font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 5px;'>1. FUNDAMENTAÇÃO TEÓRICA E INSTRUMENTO</h3>
                    <p style='font-size: 12px; text-align: justify;'>
                    A metodologia aplicada baseia-se nos princípios da gestão de riscos ocupacionais estabelecidos pela <b>NR-01</b> e diretrizes da <b>ISO 31010</b>. A avaliação utiliza a percepção dos trabalhadores como indicador fundamental para o diagnóstico do ambiente de trabalho.
                    <br><br>
                    O instrumento eleito para a coleta de dados é o <b>COPSOQ-II (Copenhagen Psychosocial Questionnaire) - Versão Média</b>, validado internacionalmente. O inventário é composto por perguntas estruturadas que avaliam Fatores de Risco específicos (ex: Ritmo de trabalho acelerado, Exigências emocionais) agrupados em 8 Dimensões macroscópicas.
                    </p>

                    <h3 style='color: #1560bd; font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 5px;'>2. METODOLOGIA DE ESCALONAMENTO E CLASSIFICAÇÃO</h3>
                    <p style='font-size: 12px; text-align: justify;'>
                    As respostas do inventário são convertidas matematicamente em percentuais (0% a 100%), onde o percentual representa o nível de exposição ou percepção negativa ao fator de risco. Para itens de percepção positiva (ex: apoio social), o sistema aplica a inversão de escore garantindo a fidedignidade do risco.
                    <br>Os resultados são enquadrados em três níveis de ação para orientar a priorização das intervenções:
                    </p>

                    <table style='width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 11px;'>
                        <tr style='background-color: #f0f0f0;'>
                            <th style='padding: 6px; border: 1px solid #ccc; text-align: center; width: 20%;'>RESULTADO</th>
                            <th style='padding: 6px; border: 1px solid #ccc; text-align: center; width: 25%;'>CLASSIFICAÇÃO</th>
                            <th style='padding: 6px; border: 1px solid #ccc; text-align: left; width: 55%;'>DIRETRIZ DE AÇÃO</th>
                        </tr>
                        <tr>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: center; font-weight: bold;'>0,0% a 49,99%</td>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: center; color: #16a34a; font-weight: bold;'>Situação Favorável</td>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: left;'>Indica uma situação controlada, onde os fatores de risco têm uma influência mínima. Manter monitoramento contínuo.</td>
                        </tr>
                        <tr>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: center; font-weight: bold;'>50,0% a 74,99%</td>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: center; color: #ca8a04; font-weight: bold;'>Situação Intermediária</td>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: left;'>Sinaliza fatores que necessitam de atenção para não evoluírem para quadros mais severos. Planejar ações preventivas.</td>
                        </tr>
                        <tr>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: center; font-weight: bold;'>75,0% a 100%</td>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: center; color: #dc2626; font-weight: bold;'>Situação Crítica</td>
                            <td style='padding: 6px; border: 1px solid #ccc; text-align: left;'>Representa um ambiente nocivo que requer intervenção imediata para mitigação de agravos à saúde física e mental.</td>
                        </tr>
                    </table>

                    <h3 style='color: #1560bd; font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 5px;'>3. INTEGRAÇÃO COM O INVENTÁRIO DE RISCOS (PGR)</h3>
                    <p style='font-size: 12px; text-align: justify;'>
                    Os resultados apurados por este inventário representam o levantamento de perigos (a Percepção do Trabalhador). Para fins de inserção no PGR, os Fatores de Risco que apresentarem índices nas faixas <b>Intermediária</b> ou <b>Crítica</b> deverão ser cruzados na <b>Matriz de Avaliação de Riscos (5x5)</b>, relacionando-os com:
                    </p>
                    <ul style='font-size: 12px;'>
                        <li><b>Severidade (1 a 5):</b> O dano ou agravo potencial à saúde (ex: Fadiga, Burnout, Acidentes).</li>
                        <li><b>Probabilidade (1 a 5):</b> A chance do dano ocorrer baseada nas frequências relatadas neste laudo e na (in)existência de medidas de controle (NR-01, 1.5.4.4.5.3).</li>
                    </ul>

                    <h3 style='color: #1560bd; font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 5px;'>4. AMOSTRAGEM E REPRESENTATIVIDADE</h3>
                    <p style='font-size: 12px; text-align: justify;'>
                    A avaliação busca o caráter censitário (participação de todos os trabalhadores). Nos casos de impossibilidade, os resultados devem respeitar o dimensionamento estratificado para garantir um nível de confiança estatística (Curva de Gauss), assegurando que todos os Grupos Similares de Exposição (GSE) estejam representados.
                    </p>
                    """, unsafe_allow_html=True)

                with tab_bruto:
                    st.markdown("### 📥 Dados Brutos e Simulação")
                    modo_simulacao = st.toggle("🔬 Habilitar Modo Simulação (Edição de Dados)", key=f"sim_toggle_{sel_c_id}")
                    
                    if not df_raw.empty:
                        df_exp = df_global[['Setor', 'Função', 'Dimensao', 'Enunciado', 'Resposta']].fillna("Não Informado")
                        
                        if modo_simulacao:
                            st.info("⚠️ **DICA:** Altere os valores numéricos (1 a 5) ou setores na tabela abaixo e clique em 'Recalcular'. Nenhuma alteração afetará o banco de dados oficial.")
                            edited_df = st.data_editor(df_exp, use_container_width=True, num_rows="fixed", key=f"editor_sim_{sel_c_id}")
                            if st.button("🔄 Recalcular Dashboard com estes Dados", type="primary"):
                                st.session_state[f'sim_data_{sel_c_id}'] = edited_df
                                st.rerun()
                        else:
                            st.dataframe(df_exp, use_container_width=True)
                            if f'sim_data_{sel_c_id}' in st.session_state:
                                del st.session_state[f'sim_data_{sel_c_id}']
                        
                        buf = io.BytesIO(); df_exp.to_excel(buf, index=False)
                        st.download_button("📥 Excel (.xlsx)", buf.getvalue(), "relatorio_bruto.xlsx", key="down_bruto_final")
                    else:
                        st.info("Aguardando as primeiras respostas para gerar os dados brutos.")

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