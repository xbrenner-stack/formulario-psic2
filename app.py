import streamlit as st
import pandas as pd
import re
from datetime import datetime, date
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
import plotly.express as px

# --- CONFIGURAÇÃO E CONSTANTES ---
# Alterado para 'expanded' para o menu do Admin aparecer aberto
st.set_page_config(page_title="SST - Pesquisas", layout="wide", initial_sidebar_state="expanded")

# --- OCULTAR ELEMENTOS DO STREAMLIT (FORÇA MÁXIMA) ---
hide_st_style = """
            <style>
            /* 1. Ocultar botões de Deploy e Menu Superior (mantendo a barra superior para a setinha do menu funcionar) */
            .stAppDeployButton {display: none !important;}
            [data-testid="stDeployButton"] {display: none !important;}
            #MainMenu {visibility: hidden !important;}

            /* 2. Ocultar Footer (Rodapé) */
            footer {visibility: hidden !important;}
            [data-testid="stFooter"] {display: none !important;}

            /* 3. Ocultar Toolbar flutuante do desenvolvedor */
            [data-testid="stToolbar"] {display: none !important;}
            [data-testid="stDecoration"] {display: none !important;}

            /* 4. Caçar e destruir a marca d'água inferior (Avatar/Hosted with) */
            [data-testid="hostedWatermark"] {display: none !important;}
            a[href*="streamlit.io/cloud"] {display: none !important;}
            [class^="viewerBadge"] {display: none !important;}
            [class*="viewerBadge"] {display: none !important;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# Endereço base para geração de links
BASE_URL = "https://formulario-psic2.streamlit.app" 

# --- BANCO DE DADOS ---
# O sistema agora ignora o arquivo local e usa a conexão segura com a HostGator
DB_URL = st.secrets["db_url"]
Base = declarative_base()

class Empresa(Base):
    __tablename__ = 'empresas'
    id = Column(Integer, primary_key=True)
    codigo_empresa = Column(String(50), unique=True, nullable=False)
    nome_empresa = Column(String(200), nullable=False)
    senha_rh = Column(String(100), nullable=False) 
    link_forms = Column(String(500), nullable=False)
    funcionarios = relationship("Funcionario", back_populates="empresa", cascade="all, delete-orphan")

class Funcionario(Base):
    __tablename__ = 'funcionarios'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey('empresas.id'), nullable=False)
    cpf = Column(String(20), nullable=False)
    nome = Column(String(200), nullable=False)
    data_nasc = Column(String(20), nullable=False)
    status = Column(String(50), default="Pendente")
    empresa = relationship("Empresa", back_populates="funcionarios")
    __table_args__ = (UniqueConstraint('empresa_id', 'cpf', name='_empresa_cpf_uc'),)

engine = create_engine(DB_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

@st.cache_resource
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
                if user.status == "Concluído":
                    st.success(f"Olá {user.nome}! Você já concluiu seu preenchimento. Obrigado!")
                    st.balloons()
                else:
                    st.session_state['logged_user_id'] = user.id
                    st.rerun()
            else:
                st.error("Dados não encontrados. Verifique seu CPF e Data de Nascimento.")

def portal_colaborador(empresa, user):
    st.title(f"Olá, {user.nome}")
    st.components.v1.iframe(empresa.link_forms, height=800, scrolling=True)
    st.divider()
    st.warning("⚠️ Importante: Após finalizar no formulário acima, confirme sua participação abaixo.")
    
    terminou = st.checkbox('Confirmo que terminei de responder.', key='confirma_form')
    if st.button("✅ JÁ FINALIZEI O PREENCHIMENTO", use_container_width=True, type="primary", disabled=not terminou):
        db = get_db()
        db_user = db.query(Funcionario).get(user.id)
        db_user.status = "Concluído"
        db.commit()
        st.success("Participação registrada!")
        st.session_state.clear()
        st.rerun()

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

    menu = st.sidebar.radio("Navegação", ["Dashboard", "Gestão de Empresas", "Gestão de Funcionários", "Sair"])
    
    if menu == "Sair":
        st.session_state.pop('admin_logged_in')
        st.rerun()

    db = get_db()

    if menu == "Dashboard":
        st.title("📊 Painel de Engajamento")
        empresas = db.query(Empresa).all()
        emp_names = [e.nome_empresa for e in empresas]
        selected_emp_name = st.selectbox("Selecione a Empresa", ["Todas"] + emp_names)
        
        query = db.query(Funcionario)
        if selected_emp_name != "Todas":
            emp = db.query(Empresa).filter_by(nome_empresa=selected_emp_name).first()
            query = query.filter_by(empresa_id=emp.id)
        
        funcionarios = query.all()
        if funcionarios:
            df = pd.DataFrame([{'Status': f.status, 'Nome': f.nome, 'CPF': f.cpf} for f in funcionarios])
            c1, c2, c3 = st.columns(3)
            total = len(df)
            concluidos = len(df[df['Status'] == 'Concluído'])
            c1.metric("Total", total)
            c2.metric("Concluídos", concluidos)
            c3.metric("Engajamento", f"{(concluidos/total*100):.1f}%" if total > 0 else "0%")
            
            fig = px.pie(df, names='Status', title="Proporção", color='Status', color_discrete_map={'Concluído':'#22c55e', 'Pendente':'#ef4444'})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nenhum funcionário cadastrado.")

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
                    if db.query(Empresa).filter_by(codigo_empresa=codigo).first():
                        st.error("Código já existe!")
                    else:
                        new_emp = Empresa(codigo_empresa=codigo, nome_empresa=nome, link_forms=link, senha_rh=senha)
                        db.add(new_emp)
                        db.commit()
                        st.success("Empresa cadastrada!")
                        st.rerun()

        st.subheader("Empresas Cadastradas")
        for emp in db.query(Empresa).all():
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.write(f"**{emp.nome_empresa}**")
                st.code(f"{BASE_URL}/?emp={emp.codigo_empresa}", language="text")
                if c2.button("Excluir", key=f"del_{emp.id}"):
                    db.delete(emp)
                    db.commit()
                    st.rerun()

    elif menu == "Gestão de Funcionários":
        st.title("👥 Gestão de Funcionários")
        empresas = db.query(Empresa).all()
        if not empresas:
            st.warning("Cadastre uma empresa primeiro.")
            return

        emp_dict = {e.nome_empresa: e.id for e in empresas}
        sel_emp = st.selectbox("Selecione a empresa", list(emp_dict.keys()))
        emp_id = emp_dict[sel_emp]
        
        with st.expander("📥 Importar Lista (Excel/CSV)"):
            up = st.file_uploader("Selecione o arquivo", type=['csv', 'xlsx'])
            if up:
                df_up = pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)
                cols = {c.lower(): c for c in df_up.columns}
                col_nome = next((v for k,v in cols.items() if 'nome' in k), df_up.columns[0])
                col_cpf = next((v for k,v in cols.items() if 'cpf' in k), df_up.columns[1])
                col_data = next((v for k,v in cols.items() if 'nasc' in k or 'data' in k), df_up.columns[2])
                
                if st.button("Confirmar Importação"):
                    count = 0
                    for _, r in df_up.iterrows():
                        cpf_limpo = limpar_cpf(r[col_cpf])
                        if cpf_limpo and not db.query(Funcionario).filter_by(empresa_id=emp_id, cpf=cpf_limpo).first():
                            data_ok = processar_data_robusta(r[col_data])
                            if data_ok:
                                f = Funcionario(empresa_id=emp_id, nome=str(r[col_nome]), cpf=cpf_limpo, data_nasc=data_ok)
                                db.add(f)
                                count += 1
                    db.commit()
                    st.success(f"{count} importados com sucesso!")
                    st.rerun()

        funcs = db.query(Funcionario).filter_by(empresa_id=emp_id).all()
        rows = []
        for f in funcs:
            try:
                d_obj = datetime.strptime(f.data_nasc, '%d/%m/%Y').date()
            except:
                d_obj = None
            rows.append({'id': f.id, 'Nome': f.nome, 'CPF': f.cpf, 'Nascimento': d_obj, 'Status': f.status})
        
        df_edit = pd.DataFrame(rows)
        if df_edit.empty:
            df_edit = pd.DataFrame(columns=['id', 'Nome', 'CPF', 'Nascimento', 'Status'])

        edited_df = st.data_editor(
            df_edit, key="editor_func", num_rows="dynamic", use_container_width=True,
            disabled=["id", "Status"],
            column_config={"id": None, "Nascimento": st.column_config.DateColumn(format="DD/MM/YYYY")}
        )
        
        if st.button("💾 Salvar Alterações"):
            for _, row in edited_df.iterrows():
                if pd.notna(row.get('id')):
                    f_db = db.query(Funcionario).get(int(row['id']))
                    if f_db:
                        f_db.nome = str(row['Nome'])
                        f_db.cpf = limpar_cpf(row['CPF'])
                        f_db.data_nasc = processar_data_robusta(row['Nascimento'])
                elif pd.notna(row.get('Nome')) and pd.notna(row.get('CPF')):
                    cpf_new = limpar_cpf(row['CPF'])
                    data_new = processar_data_robusta(row['Nascimento'])
                    if cpf_new and data_new:
                        if not db.query(Funcionario).filter_by(empresa_id=emp_id, cpf=cpf_new).first():
                            db.add(Funcionario(empresa_id=emp_id, nome=str(row['Nome']), cpf=cpf_new, data_nasc=data_new))
            db.commit()
            st.success("Alterações salvas!")
            st.rerun()

def main():
    params = st.query_params
    emp_code = params.get("emp")
    if emp_code:
        db = get_db()
        empresa = db.query(Empresa).filter_by(codigo_empresa=emp_code).first()
        if empresa:
            if 'logged_user_id' not in st.session_state:
                login_colaborador(empresa)
            else:
                user = db.query(Funcionario).get(st.session_state['logged_user_id'])
                if user: portal_colaborador(empresa, user)
                else: st.session_state.clear(); st.rerun()
        else: st.error("Empresa não encontrada.")
    else: admin_portal()

if __name__ == "__main__":
    main()
