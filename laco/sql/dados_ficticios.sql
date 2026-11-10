-- Dados 100% fictícios para demonstração (nenhuma pessoa real).
SET NAMES utf8mb4;  -- garante acentos corretos ao rodar pelo terminal
USE laco;

INSERT INTO voluntarios (apelido, regiao) VALUES
  ('Bia',    'zona-leste'),
  ('Rafa',   'zona-norte'),
  ('Seu Zé', 'centro'),
  ('Lu',     'zona-sul'),
  ('Dani',   'zona-oeste');

INSERT INTO pedidos (apelido, regiao, tipo, periodo, descricao, prioridade, status, voluntario_id) VALUES
  ('Dona Cida', 'zona-leste', 'farmacia', 'manha',
   'Preciso buscar um remédio de uso contínuo na farmácia do posto, tenho dificuldade para andar.',
   'alta', 'aberto', NULL),
  ('Seu Antônio', 'zona-norte', 'tecnologia', 'tarde',
   'Quero ajuda para marcar consulta pelo aplicativo do SUS no celular.',
   'normal', 'em_atendimento', 2),
  ('Marta', 'centro', 'acompanhamento', 'manha',
   'Sou cega e preciso de companhia para ir a uma consulta no dia 18/11.',
   'alta', 'aberto', NULL),
  ('Seu Jorge', 'zona-sul', 'compras', 'tarde',
   'Compras pequenas no mercado do bairro: arroz, leite e frutas.',
   'normal', 'concluido', 4);
