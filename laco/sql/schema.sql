-- Laço: estrutura do banco (MySQL 8.0.16 ou mais novo, por causa dos CHECK)
-- Coleta mínima (LGPD): não existem colunas para nome completo, CPF, endereço,
-- telefone, idade ou tipo de deficiência. Só o necessário para o voluntário ajudar.
-- Defesa em duas camadas: as regras validadas pela API (valores, tamanhos e
-- coerência entre status e voluntário) também são garantidas aqui pelo banco.

SET NAMES utf8mb4;  -- garante acentos corretos ao rodar pelo terminal
CREATE DATABASE IF NOT EXISTS laco
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE laco;

CREATE TABLE IF NOT EXISTS voluntarios (
  id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  apelido    VARCHAR(40)  NOT NULL,
  regiao     ENUM('centro','zona-norte','zona-sul','zona-leste','zona-oeste') NOT NULL,
  ativo      TINYINT(1)   NOT NULL DEFAULT 1,  -- voluntário é desativado, nunca apagado
  criado_em  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT ck_voluntario_apelido CHECK (CHAR_LENGTH(TRIM(apelido)) >= 2),
  CONSTRAINT ck_voluntario_ativo CHECK (ativo IN (0, 1))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pedidos (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  apelido        VARCHAR(40)  NOT NULL,
  regiao         ENUM('centro','zona-norte','zona-sul','zona-leste','zona-oeste') NOT NULL,
  tipo           ENUM('compras','farmacia','acompanhamento','tecnologia','companhia') NOT NULL,
  periodo        ENUM('manha','tarde','noite') NOT NULL,
  descricao      VARCHAR(280) NOT NULL,
  prioridade     ENUM('normal','alta') NOT NULL DEFAULT 'normal',
  status         ENUM('aberto','em_atendimento','concluido','cancelado') NOT NULL DEFAULT 'aberto',
  voluntario_id  INT UNSIGNED NULL,
  criado_em      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- RESTRICT: não deixa apagar um voluntário que tem pedidos (ele é desativado).
  -- Assim um pedido "em atendimento" nunca fica sem ninguém responsável.
  CONSTRAINT fk_pedido_voluntario FOREIGN KEY (voluntario_id)
    REFERENCES voluntarios (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_pedido_apelido   CHECK (CHAR_LENGTH(TRIM(apelido)) >= 2),
  CONSTRAINT ck_pedido_descricao CHECK (CHAR_LENGTH(TRIM(descricao)) >= 10),
  -- Coerência: aberto não tem voluntário; em atendimento sempre tem um.
  CONSTRAINT ck_pedido_status_voluntario CHECK (
    (status = 'aberto' AND voluntario_id IS NULL)
    OR (status = 'em_atendimento' AND voluntario_id IS NOT NULL)
    OR status IN ('concluido', 'cancelado')
  ),
  INDEX idx_status_regiao (status, regiao),
  INDEX idx_listagem (status, prioridade, criado_em)  -- mesma ordem do ORDER BY da central
) ENGINE=InnoDB;
