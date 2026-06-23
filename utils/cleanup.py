import os
import shutil
from config import config
from utils.logger import setup_logger

logger = setup_logger("cleanup")

def cleanup_old_results():
    """
    Deletes old analysis results from the output directories.
    """
    target_dirs = [
        config.REPORTS_DIR,
        config.ANALYTICS_DIR,
        config.REMEDIATION_DIR
    ]

    # NUNCA apagar manifestos de rollback nem o master — são a única forma de
    # desfazer renomeações já aplicadas no disco. Apagá-los já causou perda de
    # histórico antes; rollback é sagrado.
    PRESERVE_PREFIXES = ("rollback_",)

    logger.info("Iniciando limpeza de análises antigas...")

    for directory in target_dirs:
        if os.path.exists(directory):
            try:
                # Remove all files in the directory
                for filename in os.listdir(directory):
                    if filename.startswith(PRESERVE_PREFIXES):
                        logger.debug(f"Preservado (rollback): {filename}")
                        continue
                    file_path = os.path.join(directory, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                            logger.debug(f"Removido arquivo: {file_path}")
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                            logger.debug(f"Removido diretório: {file_path}")
                    except Exception as e:
                        logger.error(f"Falha ao deletar {file_path}. Motivo: {e}")
                logger.info(f"Diretório limpo (rollback preservado): {directory}")
            except Exception as e:
                logger.error(f"Erro ao acessar diretório {directory}: {e}")
        else:
            logger.info(f"Diretório não existe, pulando: {directory}")
            # Create it if it doesn't exist for the next steps
            os.makedirs(directory, exist_ok=True)
