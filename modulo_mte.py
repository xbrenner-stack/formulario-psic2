import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean, text, Text
from sqlalchemy.orm import declarative_base, sessionmaker
import os
import io
import time
import numpy as np
from PIL import Image
from fpdf import FPDF
from streamlit_drawable_canvas import st_canvas
import base64
from datetime import datetime

BaseMTE = declarative_base()

# --- MODELOS DE BANCO DE DADOS ---
class MteFatores(BaseMTE):
    __tablename__ = 'mte_fatores'
    id = Column(Integer, primary_key=True)
    fator_mte = Column(String(200), nullable=False)
    pergunta_sugerida = Column(String(1000))
    texto_pgr = Column(String(500))
    fontes_lista = Column(String(1000))
    lesoes = Column(String(500))
    cids = Column(String(200))
    plano_acao = Column(String(500))
    acompanhamento = Column(String(500))

class MteAuditorias(BaseMTE):
    __tablename__ = 'mte_auditorias'
    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, nullable=False)
    data_auditoria = Column(String(20))
    status_conclusao = Column(String(50))
    tipo_assinatura_escolhida = Column(String(100))
    nome_signatario = Column(String(100), default="")
    cargo_signatario = Column(String(100), default="")
    cpf_signatario = Column(String(20), default="")
    usuario_logado = Column(String(100), default="")
    tecnico_cpf = Column(String(20), default="")
    tecnico_registro = Column(String(50), default="")

class MteResultados(BaseMTE):
    __tablename__ = 'mte_resultados'
    id = Column(Integer, primary_key=True)
    auditoria_id = Column(Integer, ForeignKey('mte_auditorias.id'))
    fator_id = Column(Integer, ForeignKey('mte_fatores.id'))
    risco_existente = Column(Boolean, default=False)
    fontes_selecionadas = Column(String(1000))
    severidade = Column(String(50))
    observacoes_campo = Column(String(1000))

class MteEvidencias(BaseMTE):
    __tablename__ = 'mte_evidencias'
    id = Column(Integer, primary_key=True)
    auditoria_id = Column(Integer, ForeignKey('mte_auditorias.id'))
    tipo_evidencia = Column(String(50))
    foto_base64 = Column(Text)

# --- FUNÇÕES UTILITÁRIAS ---
def processar_foto_para_db(image_bytes):
    """
    Reduz o tamanho e comprime a imagem para evitar estouro de memória no Render
    e economizar espaço no banco de dados.
    """
    if not image_bytes:
        return ""
    try:
        from PIL import Image as PILImage, ImageFile
        # Evita erro em uploads mobile de arquivos corrompidos na transferência
        ImageFile.LOAD_TRUNCATED_IMAGES = True 
        
        with PILImage.open(io.BytesIO(image_bytes)) as img:
            # Comando draft para economizar RAM no celular/Render
            if img.format in ['JPEG', 'MPO']:
                img.draft('RGB', (1000, 1000))
                
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            # Limita a largura para 800px mantendo a proporção
            if img.width > 800 or img.height > 800:
                if img.width > img.height:
                    new_w = 800
                    new_h = int((800 / img.width) * img.height)
                else:
                    new_h = 800
                    new_w = int((800 / img.height) * img.width)
                img = img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
            
            buf = io.BytesIO()
            # Salva como JPEG com compressão de 60%
            img.save(buf, format='JPEG', quality=60, optimize=True)
            return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception as e:
        st.error(f"Erro ao processar imagem: {e}")
        return ""

DB_URL = st.secrets["db_url"] if "db_url" in st.secrets else "sqlite:///sst_data.db"
engineMTE = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=3600)
BaseMTE.metadata.create_all(engineMTE)
SessionLocalMTE = sessionmaker(bind=engineMTE)

def get_db_mte():
    return SessionLocalMTE()

def calcular_zenit_mte(peso_et, peso_re, peso_me, severidade_str):
    peso_pe = 1 
    pr_val = peso_et * peso_re * peso_me * peso_pe
    
    prob_str = "Alta"
    if pr_val <= 24: prob_str = "Rara"
    elif pr_val <= 104: prob_str = "Baixa"
    elif pr_val <= 242: prob_str = "Média"
    
    matriz_risco = {
        "Alta": {"Leve": "Risco Elevado", "Moderada": "Risco Elevado", "Grave": "Risco Extremo", "Gravíssima": "Risco Extremo"},
        "Média": {"Leve": "Risco Moderado", "Moderada": "Risco Moderado", "Grave": "Risco Extremo", "Gravíssima": "Risco Extremo"},
        "Baixa": {"Leve": "Risco Baixo", "Moderada": "Risco Baixo", "Grave": "Risco Elevado", "Gravíssima": "Risco Extremo"},
        "Rara": {"Leve": "Risco Baixo", "Moderada": "Risco Baixo", "Grave": "Risco Moderado", "Gravíssima": "Risco Elevado"}
    }
    
    risco_final = matriz_risco.get(prob_str, {}).get(severidade_str, "Risco Indefinido")
    
    acoes = {
        "Risco Extremo": {"criterio": "Inaceitável", "decisao": "Controlar", "aceitabilidade": "Eliminar"},
        "Risco Elevado": {"criterio": "Inaceitável", "decisao": "Controlar", "aceitabilidade": "Reduzir"},
        "Risco Moderado": {"criterio": "Incerto", "decisao": "Reavaliar / Informação Adicional", "aceitabilidade": "Reduzir ao nível mais baixo possível"},
        "Risco Baixo": {"criterio": "Aceitável", "decisao": "Manter o Nível", "aceitabilidade": "Manter o nível do risco"}
    }
    acao_sugerida = acoes.get(risco_final, {"criterio": "-", "decisao": "-", "aceitabilidade": "-"})
    
    return {"PR": pr_val, "prob_calc": prob_str, "risco": risco_final, "acao": acao_sugerida}

def popular_fatores_iniciais():
    db = get_db_mte()
    count = db.query(MteFatores).count()
    
    # Verifica se a palavra 'descarado' ainda existe no banco para forçar a atualização
    check_fator_descarado = db.query(MteFatores).filter(MteFatores.fontes_lista.like('%descarado%')).first()
    
    if (count > 0 and count < 13) or check_fator_descarado:
        db.query(MteFatores).delete()
        db.commit()
        count = 0
        
    if count == 0:
        fatores = [
            MteFatores(
                fator_mte="01. Assédio de qualquer natureza", 
                pergunta_sugerida="**🗣️ Pergunta:** \"No dia a dia, acontece de você se sentir humilhado ou perseguido de alguma forma? Tipo levar grito, receber apelido maldoso, o pessoal te isolar, inventar fofoca ou a chefia controlar até a sua ida ao banheiro?\"\n\n**💡 Dica para o Avaliador:** _Deixe a pessoa falar à vontade. Só marque as caixinhas abaixo se for algo maldoso e que acontece de forma repetitiva, e não apenas uma briga de momento._", 
                texto_pgr="Ambiente de trabalho permissivo a condutas hostis ou brincadeiras ofensivas recorrentes.", 
                fontes_lista="Dar apelidos pejorativos, Controlar o uso do banheiro, Atribuir tarefas impossíveis ou desnecessárias, Desqualificar o trabalho de forma injusta, Espalhar boatos ou críticas maliciosas, Humilhar ou menosprezar publicamente, Isolar/excluir ou ignorar, Gritar/ameaçar ou adotar tom agressivo", 
                lesoes="Transtorno mental", cids="F43, Z56.3", plano_acao="Implementar canal de denúncia confidencial e código de conduta.", acompanhamento="Auditoria dos canais de denúncia."
            ),
            MteFatores(
                fator_mte="02. Má gestão de mudanças", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Quando a empresa muda uma regra, um sistema ou uma máquina, vocês são avisados e ensinados antes, ou a mudança cai de paraquedas e vocês que se virem para aprender sozinhos?\"\n\n**💡 Dica para o Avaliador:** _O risco acontece quando a empresa implanta novidades do nada, gerando estresse, erros e medo na equipe._", 
                texto_pgr="Falta de comunicação e preparo das equipes diante de reestruturações ou novos processos operacionais.", 
                fontes_lista="Mudanças implementadas sem aviso prévio, Falta de treinamento para usar novos sistemas/máquinas, Reestruturações frequentes sem apoio ao funcionário", 
                lesoes="Transtorno mental / Estresse agudo", cids="F43", plano_acao="Estabelecer protocolo de comunicação e treinamento antecipado para mudanças operacionais.", acompanhamento="Pesquisa rápida de clima durante transições."
            ),
            MteFatores(
                fator_mte="03. Baixa clareza de papel/função", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Você sabe exatamente o que é a sua obrigação aqui, ou vira e mexe aparece gente diferente te dando ordens que não combinam umas com as outras?\"\n\n**💡 Dica para o Avaliador:** _Marque se a pessoa fica perdida sem saber a quem obedecer ou é cobrada constantemente por coisas que não são da função dela._", 
                texto_pgr="Ausência de definição clara de responsabilidades, gerando conflitos de autoridade e ordens contraditórias.", 
                fontes_lista="Receber ordens contraditórias de chefes diferentes, Falta de clareza sobre quais são suas reais obrigações, Ser cobrado por tarefas que não foram combinadas", 
                lesoes="Transtorno mental", cids="F43, Z56.4", plano_acao="Elaborar descrições de cargos precisas e unificar a cadeia de comando.", acompanhamento="Reuniões periódicas de alinhamento."
            ),
            MteFatores(
                fator_mte="04. Baixas recompensas e reconhecimento", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Quando você faz um trabalho bem feito, alguém elogia? Ou a chefia só aparece para dar bronca quando algo dá errado e você se sente desvalorizado?\"\n\n**💡 Dica para o Avaliador:** _Não é sobre a pessoa reclamar do salário. É sobre a chefia ignorar o esforço diário e só apontar o dedo nos erros._", 
                texto_pgr="Percepção de desequilíbrio entre o esforço despendido e o reconhecimento ou feedback recebido.", 
                fontes_lista="Chefia só se comunica para dar bronca ou cobrar, Inexistência de qualquer elogio ou avaliação do esforço, Sensação de ser tratado como 'não faz mais que a obrigação'", 
                lesoes="Transtorno mental", cids="Z56.3", plano_acao="Estabelecer rotina de feedback estruturado (positivo e de correção).", acompanhamento="Monitoramento de turnover e engajamento."
            ),
            MteFatores(
                fator_mte="05. Falta de suporte/apoio", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Quando surge uma dúvida ou um 'pepino' no serviço, você consegue ajuda fácil do seu chefe ou dos colegas, ou fica largado tendo que resolver tudo sozinho?\"\n\n**💡 Dica para o Avaliador:** _O risco é o isolamento operacional. A pessoa trava no serviço porque ninguém atende, explica ou ajuda._", 
                texto_pgr="Isolamento operacional e ausência de suporte técnico ou gerencial para a resolução de problemas do dia a dia.", 
                fontes_lista="Chefia ausente ou inacessível no dia a dia, Falta de colaboração e ajuda entre os próprios colegas, Ter que resolver problemas difíceis sem nenhum apoio", 
                lesoes="Transtorno mental", cids="F43", plano_acao="Criar rotina de checkpoints diários/semanais entre gestão e operação.", acompanhamento="Índice de retrabalho."
            ),
            MteFatores(
                fator_mte="06. Falta de Autonomia (Baixo Controle)", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Você consegue dar uma paradinha rápida se precisar, ou a máquina e a chefia controlam cada passo seu o tempo todo, como se você fosse um robô?\"\n\n**💡 Dica para o Avaliador:** _O risco aqui é quando o funcionário não tem liberdade nem para as necessidades básicas sem sofrer punição ou parar a produção._", 
                texto_pgr="Impossibilidade técnica ou gerencial de o trabalhador tomar decisões simples sobre o método ou ritmo de sua tarefa.", 
                fontes_lista="Ritmo de trabalho 100% imposto pela máquina ou esteira, Proibição de fazer pausas rápidas (como ir ao banheiro ou beber água), Monitoramento excessivo e punitivo de cada movimento", 
                lesoes="Transtorno mental / DORT", cids="F32, Z56", plano_acao="Revisar fluxos de aprovação, permitindo pequenas tomadas de decisão na base.", acompanhamento="Caixa de sugestões de melhorias."
            ),
            MteFatores(
                fator_mte="07. Baixa justiça organizacional", 
                pergunta_sugerida="**🗣️ Pergunta:** \"As regras e as punições aqui valem para todo mundo igual, ou tem 'panelinha' onde uns podem fazer tudo e outros levam bronca por qualquer coisinha?\"\n\n**💡 Dica para o Avaliador:** _Foque em situações claras de injustiça e favoritismo descarado que geram revolta e clima ruim na equipe._", 
                texto_pgr="Percepção de desigualdade na aplicação de normas operacionais, gerando conflitos de relacionamento.", 
                fontes_lista="Regras aplicadas de forma desigual entre os funcionários, Favoritismo da chefia com algumas pessoas, Punições dadas de forma injusta ou exagerada", 
                lesoes="Transtorno mental", cids="F43", plano_acao="Padronizar e dar transparência às regras de conduta e penalidades.", acompanhamento="Auditoria de processos internos."
            ),
            MteFatores(
                fator_mte="08. Eventos violentos/traumáticos", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Trabalhando aqui, você corre risco real de ser assaltado, ou lida direto com clientes que te xingam, ameaçam ou tentam te agredir?\"\n\n**💡 Dica para o Avaliador:** _Não confunda com grosseria leve. O risco aqui é a ameaça real de agressão, assalto ou lidar com público extremamente hostil sem proteção._", 
                texto_pgr="Exposição ocupacional a situações de ameaça à integridade física ou psicológica por parte de terceiros.", 
                fontes_lista="Ameaças constantes ou agressões vindas de clientes/público, Trabalho em local com alto risco de assalto ou violência, Falta de segurança ou barreira física para proteger o funcionário", 
                lesoes="Transtorno mental (TEPT) / Lesões físicas", cids="F43.1, Z56.6", plano_acao="Implementar barreira física ou protocolo de segurança patrimonial e treinamento de gestão de crise.", acompanhamento="Registro de incidentes violentos."
            ),
            MteFatores(
                fator_mte="09. Baixa demanda (subcarga)", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Você acaba ficando muito tempo enrolando ou sem ter o que fazer no serviço porque as tarefas são muito repetitivas, chatas e não exigem quase nada de você?\"\n\n**💡 Dica para o Avaliador:** _Risco de desmotivação profunda. A pessoa se sente inútil porque fica ociosa demais ou faz um trabalho robótico e sem sentido._", 
                texto_pgr="Ociosidade forçada ou subutilização das capacidades cognitivas do trabalhador.", 
                fontes_lista="Ficar muito tempo sem ter o que fazer no expediente, Tarefas extremamente monótonas e sem nenhum sentido, Sensação de ser inútil ou subutilizado pela empresa", 
                lesoes="Transtorno mental", cids="F32", plano_acao="Readequar quadro de funcionários ou designar trabalhadores para projetos paralelos.", acompanhamento="Análise de produtividade e tempo ocioso."
            ),
            MteFatores(
                fator_mte="10. Excesso de Demandas (Sobrecarga)", 
                pergunta_sugerida="**🗣️ Pergunta:** \"É comum você ter que pular o horário de almoço, segurar a ida ao banheiro ou fazer muita hora extra porque o volume de serviço é absurdo e falta gente para ajudar?\"\n\n**💡 Dica para o Avaliador:** _Todo lugar tem dias corridos. Só marque risco se a sobrecarga e a falta de pessoal forem a rotina diária do setor, levando a pessoa à exaustão._", 
                texto_pgr="Ausência de fluxos definidos para priorização de demandas simultâneas, gerando fadiga mental.", 
                fontes_lista="Necessidade constante de fazer horas extras, Pular ou encurtar pausas e horário de almoço frequentemente, Volume de tarefas muito maior que o tempo disponível, Falta crônica de funcionários para dar conta do serviço", 
                lesoes="Transtorno mental / Fadiga crônica", cids="F43, Z73.0", plano_acao="Definir fluxo de triagem de urgências; Centralizar entrada de pedidos em canal único.", acompanhamento="Revisão da carga de trabalho."
            ),
            MteFatores(
                fator_mte="11. Maus relacionamentos", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Como é o clima com os colegas do seu setor? O ambiente é pesado, cheio de fofoca, gente querendo derrubar o outro ou brigas o tempo todo?\"\n\n**💡 Dica para o Avaliador:** _Busque identificar se o setor é 'tóxico' por causa das fofocas e disputas constantes e pesadas entre os próprios funcionários._", 
                texto_pgr="Clima organizacional degradado, marcado por conflitos interpessoais não gerenciados pela liderança.", 
                fontes_lista="Clima pesado e hostilidade aberta entre os colegas, Muitas fofocas e invenções para prejudicar os outros, Ambiente de competição predatória onde um tenta derrubar o outro", 
                lesoes="Transtorno mental", cids="F43, Z56.4", plano_acao="Promover cultura de diálogo e treinar liderança para mediação de conflitos.", acompanhamento="Número de reclamações no RH/Gestão."
            ),
            MteFatores(
                fator_mte="12. Difícil comunicação", 
                pergunta_sugerida="**🗣️ Pergunta:** \"O barulho aqui é tão alto que atrapalha vocês conversarem sobre o serviço? Ou os rádios e telefones falham tanto que vocês acabam fazendo coisas erradas por não conseguir se comunicar?\"\n\n**💡 Dica para o Avaliador:** _Marque se a falta de comunicação adequada (por culpa do ambiente ou dos equipamentos) atrapalha de verdade o trabalho, gerando estresse e retrabalho._", 
                texto_pgr="Barreiras físicas (ruído) ou tecnológicas que impedem o fluxo adequado de informações operacionais.", 
                fontes_lista="Barulho excessivo que impede as pessoas de se ouvirem, Equipamentos de comunicação (rádios/telefones) que falham muito, Barreiras físicas que impedem a troca de informação na equipe", 
                lesoes="Transtorno mental / Estresse", cids="F43, H91", plano_acao="Fornecer dispositivos de comunicação adequados (rádios/headsets) ou melhorar isolamento acústico.", acompanhamento="Frequência de erros por falha de comunicação."
            ),
            MteFatores(
                fator_mte="13. Trabalho remoto/isolado", 
                pergunta_sugerida="**🗣️ Pergunta:** \"Você trabalha sozinho muito isolado dos outros, ou (se trabalhar de casa) tem dificuldade de desligar porque a chefia fica mandando mensagem e ligando fora do horário de serviço?\"\n\n**💡 Dica para o Avaliador:** _Foque no isolamento extremo (ficar horas sozinho sem ver ninguém) ou na invasão pesada da vida pessoal com mensagens fora de hora._", 
                texto_pgr="Falta de delimitação entre jornada laboral e vida privada ou isolamento operacional contínuo.", 
                fontes_lista="Ficar isolado dos colegas por muito tempo no posto de trabalho, Receber cobranças e mensagens constantes fora do expediente, Falta de limite entre o horário de descanso e o trabalho", 
                lesoes="Transtorno mental / Fadiga", cids="Z73.0, F43", plano_acao="Estabelecer política de 'Direito à Desconexão' e rotinas virtuais de integração da equipe.", acompanhamento="Monitoramento de horas de conexão do sistema."
            )
        ]
        db.add_all(fatores)
        db.commit()
    db.close()

# --- GERAÇÃO DE PDF OFICIAL ---
def gerar_pdf_auditoria(auditoria_id):
    db = get_db_mte()
    try:
        auditoria = db.query(MteAuditorias).get(auditoria_id)
        if not auditoria:
            return b""

        evidencia_db = db.query(MteEvidencias).filter(MteEvidencias.auditoria_id == auditoria_id).first()
        imagem_bytes = None
        
        # BLINDAGEM DE BASE64 CORROMPIDO (LIMITE DO BANCO DE DADOS)
        if evidencia_db and evidencia_db.foto_base64:
            try:
                b64_str = evidencia_db.foto_base64
                b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
                imagem_bytes = base64.b64decode(b64_str)
            except Exception:
                imagem_bytes = None
            
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, "REGISTRO DE CONSULTA - ORGANIZAÇÃO DO TRABALHO (NR-01)", ln=True, align='C')
        pdf.ln(5)
        
        pdf.set_font("Arial", '', 10)
        # TEXTO ATUALIZADO COM A REFERÊNCIA AO GUIA OFICIAL DO MTE
        texto_metodologia = (
            "Em conformidade com a NR-01 (subitem 1.5.3.3) e NR-17, este documento comprova a consulta formal aos trabalhadores para a identificação "
            "preliminar de perigos e avaliação qualitativa de fatores de riscos psicossociais, visando integração ao Programa de Gerenciamento de Riscos (PGR). "
            "A nomenclatura e a numeração dos fatores de risco avaliados neste laudo (ex: 01 a 13) foram extraídas na íntegra do Guia Técnico Oficial do Ministério do Trabalho e Emprego (MTE)."
        )
        pdf.multi_cell(0, 5, texto_metodologia)
        pdf.ln(8)
        
        resultados = db.query(MteResultados, MteFatores).join(
            MteFatores, MteResultados.fator_id == MteFatores.id
        ).filter(MteResultados.auditoria_id == auditoria_id).all()
        
        if not resultados:
            pdf.set_font("Arial", 'I', 11)
            pdf.multi_cell(0, 6, "Após consulta e observação técnica em campo, não foram identificados fatores de risco cuja causa-raiz seja a organização do trabalho.")
            pdf.ln(5)
        else:
            for res, fator in resultados:
                pdf.set_font("Arial", 'B', 11)
                pdf.multi_cell(0, 6, f"Fator Identificado: {fator.fator_mte}")
                pdf.set_font("Arial", '', 10)
                pdf.multi_cell(0, 5, f"Fontes Relatadas/Observadas: {res.fontes_selecionadas}")
                pdf.multi_cell(0, 5, f"Severidade da Exposição: {res.severidade}")
                pdf.multi_cell(0, 5, f"Possíveis Agravos (CIDs): {fator.cids}")
                pdf.multi_cell(0, 5, f"Ação Sugerida: {fator.plano_acao}")
                if res.observacoes_campo:
                    pdf.multi_cell(0, 5, f"Nota do Avaliador: {res.observacoes_campo}")
                pdf.ln(4)
                
        tipo_assinatura = str(auditoria.tipo_assinatura_escolhida) if auditoria else "Não especificado"
        
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(0, 8, "COMPROVAÇÃO DE CONSULTA E AVALIAÇÃO (NR-01)", ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.multi_cell(0, 5, f"Mecanismo de evidência: {tipo_assinatura}.")
        pdf.ln(3)
        pdf.set_font("Arial", 'I', 8)
        pdf.multi_cell(0, 4, "Nota Legal: Este documento constitui evidência primária de campo. Sua validade técnica consolida-se mediante a assinatura e/ou evidência visual anexa para comprovação junto ao PGR.")
        
        if imagem_bytes is not None:
            temp_img = "temp_evidencia_pgr.jpg"
            with open(temp_img, "wb") as f:
                f.write(imagem_bytes)
            pdf.ln(5)
            try:
                from PIL import Image as PILImage
                with PILImage.open(temp_img) as img:
                    w, h = img.size
                    aspect = h / w
                    img_h = 80 * aspect
                    
                    curr_y = pdf.get_y()
                    if curr_y + img_h > 240:
                        pdf.add_page()
                        curr_y = pdf.get_y()
                    
                    pdf.image(temp_img, x=65, y=curr_y, w=80)
                    pdf.set_y(curr_y + img_h + 5)
            except Exception:
                pass
            if os.path.exists(temp_img):
                os.remove(temp_img)
        else:
            pdf.ln(15)
            
        # --- LÓGICA DE ASSINATURA CONDICIONAL ---
        # Não imprime linha de assinatura para RAT (1), Fé Pública (5) ou Lista DDS (6)
        if not (tipo_assinatura.startswith("1") or tipo_assinatura.startswith("5") or tipo_assinatura.startswith("6")):
            y_assinaturas = pdf.get_y()
            if y_assinaturas > 260:
                pdf.add_page()
                y_assinaturas = pdf.get_y()
                
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(0, 5, "________________________________________________________", ln=True, align='C')
            
            txt_nome = auditoria.nome_signatario if auditoria.nome_signatario else "Assinatura do Respondente"
            pdf.cell(0, 5, txt_nome, ln=True, align='C')
            
            pdf.set_font("Arial", '', 9)
            titulo_signatario = "Trabalhador Consultado (Amostragem NR-01)"
            if tipo_assinatura.startswith("2."):
                titulo_signatario = "Responsável pelo Setor / Turno Avaliado"
                
            txt_cargo_cpf = f"{titulo_signatario}"
            if auditoria.cargo_signatario:
                txt_cargo_cpf += f" | {auditoria.cargo_signatario}"
            if auditoria.cpf_signatario:
                txt_cargo_cpf += f" - CPF: {auditoria.cpf_signatario}"
                
            pdf.cell(0, 4, txt_cargo_cpf, ln=True, align='C')
        
        # RODAPÉ COM CARIMBO DO AVALIADOR
        # O espaçamento dinâmico ln(15) impede que o FPDF pule para uma página em branco
        pdf.ln(15)
        pdf.set_font("Arial", 'I', 8)
        
        texto_rodape = f"Levantamento conduzido em campo por: {auditoria.usuario_logado}"
        if auditoria.tecnico_cpf:
            texto_rodape += f" | CPF: {auditoria.tecnico_cpf}"
        if auditoria.tecnico_registro:
            texto_rodape += f" | Registro Profissional: {auditoria.tecnico_registro}"
            
        pdf.cell(0, 5, texto_rodape, ln=True, align='C')
        
        data_h = datetime.now()
        pdf.cell(0, 5, f"Data e Hora da Geração do Arquivo: {data_h.strftime('%d/%m/%Y %H:%M')}", ln=True, align='C')
                
        out = pdf.output(dest='S')
        return out.encode('latin1', errors='replace') if isinstance(out, str) else bytes(out)
    finally:
        db.close()

# --- INTERFACE PRINCIPAL ---
def renderizar_auditoria_mte(emp_id, tecnico_nome):
    popular_fatores_iniciais()
    
    st.title('📋 Auditoria Qualitativa (NR-01 e NR-17)')
    st.write("Identificação de perigos e consulta aos trabalhadores.")
    
    aba_nova, aba_historico, aba_gabarito = st.tabs(["📝 Nova/Editar Auditoria", "📂 Histórico e Impressão", "📑 Gabarito Zenit"])
    
    db = get_db_mte()
    try:
        # GERENCIAMENTO DE ESTADO PARA EDIÇÃO
        if 'mte_edit_id' not in st.session_state:
            st.session_state['mte_edit_id'] = None

        aud_obj_carregado = None
        if st.session_state['mte_edit_id']:
            aud_obj_carregado = db.query(MteAuditorias).get(st.session_state['mte_edit_id'])
            if not aud_obj_carregado:
                st.session_state['mte_edit_id'] = None
                
        key_suf = str(aud_obj_carregado.id) if aud_obj_carregado else "new"

        # ==========================================
        # ABA 1: NOVA / EDITAR AUDITORIA
        # ==========================================
        with aba_nova:
            if aud_obj_carregado:
                st.info(f"✏️ **Modo de Edição:** Editando auditoria iniciada em {aud_obj_carregado.data_auditoria} (Status: {aud_obj_carregado.status_conclusao})")
                if st.button("❌ Cancelar Edição e Voltar", key=f"btn_cancela_{key_suf}"):
                    st.session_state['mte_edit_id'] = None
                    st.rerun()
            else:
                st.info("🆕 Iniciando um novo levantamento de campo.")

            fatores = db.query(MteFatores).all()
            
            # Carregar resultados prévios caso seja edição
            dict_resultados = {}
            if aud_obj_carregado:
                for r in db.query(MteResultados).filter_by(auditoria_id=aud_obj_carregado.id).all():
                    dict_resultados[r.fator_id] = r
            
            help_severidade = "🟢 Leve: Estresse passageiro, sem adoecimento. | 🟡 Moderada: Gera sofrimento contínuo, insônia, atestado. | 🔴 Grave: Dano crônico, Burnout, incapacidade."
            
            for fator in fatores:
                r_atual = dict_resultados.get(fator.id)
                def_identificado = r_atual is not None
                def_fontes = [f.strip() for f in r_atual.fontes_selecionadas.split(',')] if r_atual and r_atual.fontes_selecionadas else []
                def_sev = r_atual.severidade if r_atual and r_atual.severidade else "Leve"
                idx_sev = ["Leve", "Moderada", "Grave"].index(def_sev) if def_sev in ["Leve", "Moderada", "Grave"] else 0
                def_obs = r_atual.observacoes_campo if r_atual else ""

                with st.expander(fator.fator_mte):
                    st.markdown(fator.pergunta_sugerida)
                    identificado = st.toggle("Identificar Risco", value=def_identificado, key=f"toggle_{fator.id}_{key_suf}")
                    if identificado:
                        fontes_opcoes = [f.strip() for f in fator.fontes_lista.split(',')] if fator.fontes_lista else []
                        valid_def_fontes = [f for f in def_fontes if f in fontes_opcoes]
                        
                        st.multiselect("Fontes Observadas (Selecione)", options=fontes_opcoes, default=valid_def_fontes, key=f"fontes_{fator.id}_{key_suf}")
                        st.caption(f"_{help_severidade}_")
                        st.selectbox("Severidade do Dano (Critério Médico/Ocupacional)", options=["Leve", "Moderada", "Grave"], index=idx_sev, key=f"sev_{fator.id}_{key_suf}")
                        st.text_area("Observações de Campo (Opcional)", value=def_obs, key=f"obs_{fator.id}_{key_suf}")
                        
            st.divider()
            st.subheader("Evidência de Consulta (NR-01)")
            
            opcoes_comprovacao = [
                "1. Fluxo Híbrido (Foto da RAT Física)",
                "2. Atestado do Responsável do Turno (Assinatura Eletrônica)",
                "3. Representante Amostral (Assinatura Eletrônica)",
                "4. Modo Não Alfabetizado (Impressão Digital)",
                "5. Fé Pública do Avaliador (Diário de Campo)",
                "6. Inserção em Lista de DDS/OS"
            ]
            
            idx_comp = 0
            if aud_obj_carregado and aud_obj_carregado.tipo_assinatura_escolhida in opcoes_comprovacao:
                idx_comp = opcoes_comprovacao.index(aud_obj_carregado.tipo_assinatura_escolhida)
            
            tipo_comprovacao = st.radio("Selecione o mecanismo probatório:", opcoes_comprovacao, index=idx_comp, key=f"rad_tipo_{key_suf}")
            
            # RAIO-X DE PROTEÇÃO DE EVIDÊNCIA E BLINDAGEM DE BASE64
            ev_obj = None
            if aud_obj_carregado:
                ev_obj = db.query(MteEvidencias).filter_by(auditoria_id=aud_obj_carregado.id).first()
            
            substituir_ev = False
            if ev_obj and ev_obj.foto_base64:
                st.success("✅ **Evidência Protegida:** Uma prova documental já está armazenada no banco para esta auditoria.")
                try:
                    b64_str = ev_obj.foto_base64
                    b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
                    st.image(base64.b64decode(b64_str), width=300)
                except Exception:
                    st.error("⚠️ Esta foto foi corrompida pelo limite antigo do banco de dados e não pode ser exibida.")
                    
                substituir_ev = st.toggle("🔄 Descartar e Capturar Nova Evidência", key=f"subs_ev_{key_suf}")
            
            evidencia_bytes = None
            nome_s = aud_obj_carregado.nome_signatario if aud_obj_carregado else ""
            cargo_s = aud_obj_carregado.cargo_signatario if aud_obj_carregado else ""
            cpf_s = aud_obj_carregado.cpf_signatario if aud_obj_carregado else ""

            if not ev_obj or substituir_ev:
                if tipo_comprovacao in ["1. Fluxo Híbrido (Foto da RAT Física)", "4. Modo Não Alfabetizado (Impressão Digital)", "5. Fé Pública do Avaliador (Diário de Campo)", "6. Inserção em Lista de DDS/OS"]:
                    st.info("💡 **Dica:** Tire uma foto ou selecione na galeria (a compactação para o banco de dados é feita automaticamente).")
                    
                    foto_capturada = st.file_uploader(
                        "📸 Capturar Foto ou Selecionar arquivo", 
                        type=['jpg', 'jpeg', 'png'], 
                        key=f"up_geral_{key_suf}"
                    )
                    if foto_capturada:
                        evidencia_bytes = foto_capturada.getvalue()
                        st.success("✅ Arquivo de foto anexado com sucesso!")
                        
                    # Se for a Opção 1, 5 ou 6, não mostrar campos de Nome e Cargo do trabalhador individual
                    if tipo_comprovacao.startswith("1") or tipo_comprovacao.startswith("5") or tipo_comprovacao.startswith("6"):
                        nome_s = ""
                        cargo_s = ""
                        cpf_s = ""
                    else:
                        st.write("✏️ **Identificação do Signatário / Documento:**")
                        nome_s = st.text_input("Nome do Trabalhador / Título do Documento", value=nome_s, key=f"nome_hyb_{key_suf}")
                        c1, c2 = st.columns(2)
                        cargo_s = c1.text_input("Setor/Cargo", value=cargo_s, key=f"cargo_hyb_{key_suf}")
                        cpf_s = c2.text_input("CPF (Opcional)", value=cpf_s, key=f"cpf_hyb_{key_suf}")
                        
                elif tipo_comprovacao in ["2. Atestado do Responsável do Turno (Assinatura Eletrônica)", "3. Representante Amostral (Assinatura Eletrônica)"]:
                    st.info("Busque o trabalhador ou adicione manualmente se não for registrado.")
                    funcionarios = []
                    try:
                        res_func = db.execute(text("SELECT nome, funcao, cpf FROM funcionarios WHERE empresa_id = :e_id ORDER BY nome ASC"), {"e_id": emp_id}).fetchall()
                        for r in res_func: funcionarios.append({"nome": r[0], "funcao": r[1], "cpf": r[2]})
                    except Exception: pass
                        
                    opcoes_func = [f"{f['nome']} ({f['funcao']})" if f['funcao'] else f['nome'] for f in funcionarios]
                    opcoes_func.append("➕ Adicionar Manualmente (Sócio, Diretor, Não Cadastrado)")
                    
                    selecao_func = st.selectbox("Buscar Funcionário", options=opcoes_func, index=None, key=f"sel_func_{key_suf}")
                    
                    if selecao_func == "➕ Adicionar Manualmente (Sócio, Diretor, Não Cadastrado)":
                        nome_s = st.text_input("Nome Completo", value=nome_s, key=f"nome_man_{key_suf}")
                        c1, c2 = st.columns(2)
                        cargo_s = c1.text_input("Cargo (Ex: Sócio, Gerente)", value=cargo_s, key=f"cargo_man_{key_suf}")
                        cpf_s = c2.text_input("CPF", value=cpf_s, key=f"cpf_man_{key_suf}")
                    elif selecao_func:
                        for f in funcionarios:
                            match_str = f"{f['nome']} ({f['funcao']})" if f['funcao'] else f['nome']
                            if match_str == selecao_func:
                                nome_s = f['nome']
                                c1, c2 = st.columns(2)
                                cargo_s = c1.text_input("Cargo", value=(f['funcao'] or ""), disabled=True, key=f"c_bloq_{key_suf}")
                                cpf_s = c2.text_input("CPF", value=(f['cpf'] or ""), disabled=True, key=f"cp_bloq_{key_suf}")
                                break
                    
                    st.write("Assinatura na Tela:")
                    cv = st_canvas(stroke_width=2, stroke_color="#000", background_color="#FFF", height=150, key=f"cv_ass_{key_suf}")
                    if cv.image_data is not None:
                        if np.any(cv.image_data[:, :, 3] > 0):
                            buf = io.BytesIO()
                            Image.fromarray(cv.image_data.astype('uint8')).convert('RGB').save(buf, format="JPEG")
                            evidencia_bytes = buf.getvalue()
            else:
                # Edição de texto quando já existe evidência protegida
                if tipo_comprovacao.startswith("1") or tipo_comprovacao.startswith("5") or tipo_comprovacao.startswith("6"):
                    nome_s = ""
                    cargo_s = ""
                    cpf_s = ""
                else:
                    st.write("✏️ **Revisar dados do signatário (Apenas Texto):**")
                    nome_s = st.text_input("Nome Completo", value=nome_s, key=f"nome_ed_{key_suf}")
                    c1, c2 = st.columns(2)
                    cargo_s = c1.text_input("Cargo/Setor", value=cargo_s, key=f"cargo_ed_{key_suf}")
                    cpf_s = c2.text_input("CPF", value=cpf_s, key=f"cpf_ed_{key_suf}")

            st.divider()
            c_btn1, c_btn2 = st.columns(2)
            salvar_rascunho = c_btn1.button("💾 Salvar Rascunho", use_container_width=True)
            finalizar_aud = c_btn2.button("🔒 Finalizar Auditoria", type="primary", use_container_width=True)

            if salvar_rascunho or finalizar_aud:
                status_final = "Concluída" if finalizar_aud else "Em Andamento"
                
                cpf_do_tecnico = st.session_state.get('cpf_avaliador', '')
                registro_do_tecnico = st.session_state.get('registro_avaliador', '')

                if aud_obj_carregado:
                    aud_obj_carregado.data_auditoria = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    aud_obj_carregado.status_conclusao = status_final
                    aud_obj_carregado.tipo_assinatura_escolhida = tipo_comprovacao
                    aud_obj_carregado.nome_signatario = nome_s
                    aud_obj_carregado.cargo_signatario = cargo_s
                    aud_obj_carregado.cpf_signatario = cpf_s
                    aud_obj_carregado.usuario_logado = tecnico_nome
                    aud_obj_carregado.tecnico_cpf = cpf_do_tecnico
                    aud_obj_carregado.tecnico_registro = registro_do_tecnico
                    
                    db.query(MteResultados).filter_by(auditoria_id=aud_obj_carregado.id).delete()
                    aud_id_final = aud_obj_carregado.id
                else:
                    nova_aud = MteAuditorias(
                        empresa_id=emp_id, 
                        data_auditoria=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                        status_conclusao=status_final, 
                        tipo_assinatura_escolhida=tipo_comprovacao, 
                        nome_signatario=nome_s, 
                        cargo_signatario=cargo_s, 
                        cpf_signatario=cpf_s, 
                        usuario_logado=tecnico_nome,
                        tecnico_cpf=cpf_do_tecnico,
                        tecnico_registro=registro_do_tecnico
                    )
                    db.add(nova_aud)
                    db.flush() 
                    aud_id_final = nova_aud.id
                
                riscos_salvos = 0
                for f in fatores:
                    if st.session_state.get(f"toggle_{f.id}_{key_suf}"):
                        fontes = st.session_state.get(f"fontes_{f.id}_{key_suf}", [])
                        db.add(MteResultados(
                            auditoria_id=aud_id_final, 
                            fator_id=f.id, 
                            risco_existente=True, 
                            fontes_selecionadas=", ".join(fontes), 
                            severidade=st.session_state.get(f"sev_{f.id}_{key_suf}", ""), 
                            observacoes_campo=st.session_state.get(f"obs_{f.id}_{key_suf}", "")
                        ))
                        riscos_salvos += 1
                
                # Salvar a evidência (se houver e precisar substituir)
                if substituir_ev or not ev_obj:
                    if evidencia_bytes:
                        db.query(MteEvidencias).filter_by(auditoria_id=aud_id_final).delete()
                        db.add(MteEvidencias(
                            auditoria_id=aud_id_final, 
                            tipo_evidencia="EVIDENCIA_BASE64", 
                            foto_base64=processar_foto_para_db(evidencia_bytes)
                        ))
                
                db.commit()
                st.session_state['mte_edit_id'] = None
                st.success(f"✅ Documento salvo! Status: {status_final}. Riscos computados: {riscos_salvos}.")
                time.sleep(1.5)
                st.rerun()

        # ==========================================
        # ABA 2: HISTÓRICO E IMPRESSÃO (PREVIEW)
        # ==========================================
        with aba_historico:
            st.markdown("### 🖨️ Central de Laudos do PGR")
            auditorias_empresa = db.query(MteAuditorias).filter_by(empresa_id=emp_id).order_by(MteAuditorias.id.desc()).all()
            
            if not auditorias_empresa:
                st.info("Nenhuma auditoria registrada no banco de dados desta empresa.")
            else:
                opcoes_hist = {f"[{a.status_conclusao}] Data: {a.data_auditoria} | Avaliador: {a.usuario_logado} (ID: {a.id})": a.id for a in auditorias_empresa}
                aud_hist_selecionada = st.selectbox("Selecione a visita para visualizar/editar:", list(opcoes_hist.keys()))
                id_aud = opcoes_hist[aud_hist_selecionada]
                
                aud_data = db.query(MteAuditorias).get(id_aud)
                
                with st.container(border=True):
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        st.markdown(f"**Identificação:** {aud_data.tipo_assinatura_escolhida}")
                        if aud_data.nome_signatario and not (str(aud_data.tipo_assinatura_escolhida).startswith("1") or str(aud_data.tipo_assinatura_escolhida).startswith("5") or str(aud_data.tipo_assinatura_escolhida).startswith("6")):
                            st.markdown(f"**Consultado:** {aud_data.nome_signatario} ({aud_data.cargo_signatario})")
                        
                        resultados_hist = db.query(MteResultados, MteFatores).join(MteFatores).filter(MteResultados.auditoria_id == id_aud, MteResultados.risco_existente == True).all()
                        st.markdown("**Riscos Apontados no Dia:**")
                        if not resultados_hist:
                            st.write("- Nenhum risco identificado nesta visita.")
                        else:
                            for res, fat in resultados_hist:
                                st.write(f"- {fat.fator_mte} (Severidade: {res.severidade})")
                    
                    with c2:
                        st.markdown("**Evidência Armazenada:**")
                        evi_data = db.query(MteEvidencias).filter_by(auditoria_id=id_aud).first()
                        
                        # BLINDAGEM DE BASE64 CORROMPIDO (LIMITE DO BANCO DE DADOS)
                        if evi_data and evi_data.foto_base64:
                            try:
                                b64_str = evi_data.foto_base64
                                b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
                                st.image(base64.b64decode(b64_str), use_container_width=True)
                            except Exception:
                                st.error("⚠️ Esta foto foi corrompida pelo limite antigo do banco de dados e não pode ser exibida.")
                        else:
                            st.warning("Sem imagem atrelada no banco.")
                
                c_hist1, c_hist2 = st.columns(2)
                
                with c_hist1:
                    if st.button("✏️ Reabrir para Edição", use_container_width=True):
                        st.session_state['mte_edit_id'] = id_aud
                        st.rerun()
                        
                with c_hist2:
                    st.download_button(
                        label="📥 Baixar Laudo Oficial em PDF",
                        data=gerar_pdf_auditoria(id_aud),
                        file_name=f"Auditoria_MTE_NR01_{id_aud}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary"
                    )

        # ==========================================
        # ABA 3: GABARITO ZENIT
        # ==========================================
        with aba_gabarito:
            st.markdown("""
            <style>
            @media print {
                @page { margin: 15mm !important; }
                body { zoom: 0.90 !important; color: black !important; }
                header, footer, [data-testid="stSidebar"], [data-testid="stHeader"], .stButton { display: none !important; }
                h1, [data-testid="stExpander"], [data-testid="stSelectbox"], div[data-baseweb="tab-list"], .no-print { display: none !important; }
                .appview-container, .stApp, .main, .block-container { max-width: 100% !important; padding-top: 0 !important; margin-top: 0 !important; padding-bottom: 0 !important;}
                * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color: black !important; opacity: 1 !important; filter: none !important; transition: none !important; }
                .print-gabarito-doc { display: block !important; }
            }
            @media screen {
                .print-gabarito-doc { display: none !important; }
            }
            </style>
            """, unsafe_allow_html=True)

            if not auditorias_empresa:
                st.info("Nenhum histórico para gerar gabarito.")
            else:
                opcoes_aud_gab = {f"Gabarito da Visita: {a.data_auditoria} (Avaliador: {a.usuario_logado})": a.id for a in auditorias_empresa}
                aud_gab_selecionada = st.selectbox("Selecione a base de dados para o Zenit:", list(opcoes_aud_gab.keys()))
                aud_gab_id = opcoes_aud_gab[aud_gab_selecionada]
                
                if st.button("🖨️ Imprimir Gabarito Completo"):
                    script = f"<script>setTimeout(function() {{ window.parent.print(); }}, 800);</script><div style='display:none;'>{time.time()}</div>"
                    st.components.v1.html(script, height=0)

                st.markdown("### 📑 Gabarito MTE para o Software Zenit")
                st.info("💡 **Como usar:** O sistema cruzou a Severidade e o Volume de Sintomas apontados pelo avaliador para sugerir os Pesos do Zenit.")
                
                resultados_gab = db.query(MteResultados, MteFatores).join(MteFatores).filter(MteResultados.auditoria_id == aud_gab_id, MteResultados.risco_existente == True).all()
                
                if not resultados_gab:
                    st.success("O Avaliador não identificou nenhum risco da organização do trabalho nesta auditoria.")
                else:
                    html_print_gabarito = f'''
<div class="print-gabarito-doc">
<h2 style="text-align: center; color: #1560bd; border-bottom: 2px solid #ccc; padding-bottom: 10px;">GABARITO DE IMPORTAÇÃO - SISTEMA ZENIT (MTE)</h2>
<p style="text-align: center; font-size: 14px; margin-bottom: 30px;"><b>{aud_gab_selecionada}</b></p>
'''
                    for res, fator in resultados_gab:
                        num_fontes = len([f for f in (res.fontes_selecionadas or "").split(',') if f.strip()])
                        sev = res.severidade
                        
                        peso_sugerido = 3
                        if sev == "Leve": peso_sugerido = 3 if num_fontes <= 1 else 5
                        elif sev == "Moderada": peso_sugerido = 5 if num_fontes <= 2 else 7
                        elif sev == "Grave": peso_sugerido = 7 if num_fontes <= 3 else 9
                        peso_index = [1, 3, 5, 7, 9].index(peso_sugerido)
                        
                        texto_fontes_combo = res.fontes_selecionadas
                        if res.observacoes_campo:
                            texto_fontes_combo += f"\n\nObservação de campo: {res.observacoes_campo}"

                        with st.expander(f"⚠️ {fator.fator_mte} (Severidade do Avaliador: {sev})"):
                            c1, c2 = st.columns([2, 1])
                            with c1:
                                st.markdown("##### 📝 Textos para Cadastro no Zenit")
                                st.text_area("Perigo:", value=fator.fator_mte, height=68, key=f"p_{fator.id}")
                                st.text_area("CIDs:", value=fator.cids, height=68, key=f"c_{fator.id}")
                                st.text_area("Fontes:", value=texto_fontes_combo, height=100, key=f"f_{fator.id}")
                                st.text_area("Plano de Ação:", value=fator.plano_acao, height=100, key=f"pl_{fator.id}")
                                st.text_area("Acompanhamento:", value=fator.acompanhamento, height=100, key=f"ac_{fator.id}")
                            
                            with c2:
                                st.markdown("##### ⚙️ Pesos (Aba Avaliação)")
                                st.markdown(f"**Severidade Base:** `{sev}`")
                                # SIGLAS EXPLICADAS COM O COMANDO HELP
                                peso_et = st.selectbox("Probabilidade - Exigência da Tarefa (ET):", [1, 3, 5, 7, 9], index=peso_index, key=f"et_{fator.id}", help="Mede o quanto a tarefa exige do trabalhador ou a frequência de exposição.")
                                peso_re = st.selectbox("Probabilidade - Requisitos Legais/NRs (RE):", [1, 3, 5, 7, 9], index=peso_index, key=f"re_{fator.id}", help="Avalia se a empresa está descumprindo o que a NR manda.")
                                peso_me = st.selectbox("Probabilidade - Medidas de Prevenção (ME):", [1, 3, 5, 7, 9], index=peso_index, key=f"me_{fator.id}", help="Avalia se a empresa já tem alguma medida de controle (ex: canal de denúncia).")
                                
                                calc = calcular_zenit_mte(peso_et, peso_re, peso_me, sev)
                                st.divider()
                                st.markdown("##### 🎯 Resultado Esperado (Zenit)")
                                st.markdown(f"**Nível:** `{calc['risco']}`")
                                st.markdown(f"**Ação:** `{calc['acao']['decisao']}`")

                        html_print_gabarito += f'''
<div style="margin-bottom: 25px; page-break-inside: avoid; border: 1px solid #000; padding: 15px; border-radius: 5px;">
<h3 style="color: #000; margin-top: 0; border-bottom: 1px solid #ccc; padding-bottom: 5px;">⚠️ {fator.fator_mte}</h3>
<table style="width: 100%; font-size: 12px; border-collapse: collapse;">
<tr>
<td style="width: 65%; vertical-align: top; padding-right: 15px;">
<p style="margin: 0 0 5px 0;"><b>Perigo:</b> {fator.fator_mte}</p>
<p style="margin: 0 0 5px 0;"><b>Lesões (CIDs):</b> {fator.cids}</p>
<p style="margin: 0 0 5px 0;"><b>Fontes:</b><br>{texto_fontes_combo}</p>
<p style="margin: 0 0 5px 0;"><b>Plano de Ação:</b><br>{fator.plano_acao}</p>
<p style="margin: 0 0 0 0;"><b>Acompanhamento:</b><br>{fator.acompanhamento}</p>
</td>
<td style="width: 35%; vertical-align: top; background-color: #f4f4f4; padding: 10px; border-left: 1px solid #ccc;">
<h4 style="margin: 0 0 10px 0; color:#000; font-size: 13px;">Parâmetros Zenit</h4>
<p style="margin: 0 0 3px 0;"><b>Severidade:</b> {sev}</p>
<p style="margin: 0 0 3px 0;"><b>Prob. Exigência da Tarefa (ET):</b> Peso {peso_et}</p>
<p style="margin: 0 0 3px 0;"><b>Prob. Requisitos Legais (RE):</b> Peso {peso_re}</p>
<p style="margin: 0 0 3px 0;"><b>Prob. Medidas Prevenção (ME):</b> Peso {peso_me}</p>
<p style="margin: 0 0 10px 0;"><b>Prob. NR09 (PE):</b> Peso 1</p>
<p style="margin: 0 0 3px 0; border-top: 1px solid #ccc; padding-top: 5px;"><b>Probabilidade Final:</b> {calc['prob_calc']} (PR: {calc['PR']})</p>
<p style="margin: 0 0 3px 0;"><b>Nível do Risco:</b> {calc['risco']}</p>
<p style="margin: 0 0 0 0;"><b>Decisão:</b> {calc['acao']['decisao']}</p>
</td>
</tr>
</table>
</div>
'''
                    html_print_gabarito += "</div>"
                    st.markdown(html_print_gabarito, unsafe_allow_html=True)
    finally:
        db.close()