# http-range-tools

Biblioteca e CLI para interpretar o campo HTTP `Range` e calcular intervalos de bytes sem acessar arquivos ou rede. Python 3.10+, sem dependências de execução. [Documentação completa em inglês](README.md).

É útil para ferramentas de arquivos estáticos, integrações web e diagnóstico: distingue sintaxe inválida, unidade desconhecida e intervalos válidos que ficam fora da representação.

## Uso

Em um checkout local:

```sh
python -m pip install .
http-range-tools --size 12 'bytes=2-4,-2'
```

Também é possível executar diretamente do código-fonte:

```sh
PYTHONPATH=src python -m http_range_tools --size 12 'bytes=2-4,-2'
PYTHONPATH=src python examples/synthetic_slices.py
```

```python
from http_range_tools import resolve_range

resultado = resolve_range("bytes=2-4,30-,-2", size=12)
assert resultado.satisfiable
assert resultado.unsatisfied_count == 1
assert [(p.start, p.stop) for p in resultado.ranges] == [(2, 5), (10, 12)]
```

O limite final do HTTP é inclusivo. A biblioteca retorna intervalos no formato de fatias do Python: `2-4` vira `[2:5]`, com três bytes. Informe o tamanho da representação selecionada; se houver codificação de conteúdo, use o tamanho da sequência codificada.

`parse_range` retorna uma tupla imutável de `ClosedRange(first, last)`, `OpenRange(first)` ou `SuffixRange(length)`. `resolve_ranges` recebe uma sequência não vazia desses objetos e um tamanho. `resolve_range` combina as duas operações. O resultado contém `size`, `ranges`, `satisfiable` e `unsatisfied_count`; cada intervalo possui `start`, `stop` e a propriedade `length`.

A ordem, as sobreposições e os intervalos repetidos são preservados. Membros insatisfatíveis são descartados e contados. Um membro invertido, como `8-7`, invalida todo o campo.

## CLI e erros

A CLI imprime JSON com inteiros exatos, inclusive para números muito grandes:

```json
{"size":12,"ranges":[{"start":2,"stop":5,"length":3},{"start":10,"stop":12,"length":2}],"satisfiable":true,"unsatisfied_count":0}
```

| Código de saída | Significado |
|---:|---|
| 0 | Pelo menos um membro satisfatível; JSON em stdout |
| 1 | Campo válido, mas todos os membros insatisfatíveis; JSON em stdout |
| 2 | Erro de entrada; mensagem em stderr e stdout vazio |

Erros de análise usam JSON com `error.code`: `invalid_range`, `limit_exceeded` ou `unsupported_unit`. Erros de argumentos mostram a ajuda de uso. Na API, esses códigos correspondem a `RangeSyntaxError`, `RangeLimitError` e `UnsupportedRangeUnit`, subclasses de `RangeError`. A unidade desconhecida fica em `.unit`, em minúsculas. Mensagens textuais podem mudar.

Tamanhos e limites devem ser inteiros; Booleanos são rejeitados. Tamanho negativo gera `ValueError`, tipo incorreto gera `TypeError`. Esses erros nunca viram um resultado insatisfatível.

## Limites e casos importantes

- O padrão aceita até **8192 caracteres ASCII** no campo original e **16 membros não vazios**. Os valores exatos dos limites são aceitos. Use `max_header_length`/`max_ranges` ou `--max-header-length`/`--max-ranges` para configurar limites positivos.
- Até **16 membros vazios entre vírgulas** são ignorados. Uma lista inteiramente vazia é inválida.
- Somente os dígitos ASCII `0`–`9` são aceitos. Zeros à esquerda são permitidos. Espaço e tabulação podem cercar o campo e seus membros, mas não aparecer dentro de um intervalo nem entre a unidade e `=`. CR/LF, controles e caracteres Unicode são rejeitados.
- A unidade `bytes` não diferencia maiúsculas de minúsculas. Outras unidades geram um erro próprio sem interpretar o conteúdo.
- Números com milhares de dígitos são tratados dentro do limite do campo, sem alterar configurações globais do Python. `--size` aceita de 1 a 8192 dígitos decimais ASCII; leitores do JSON precisam suportar os inteiros correspondentes.
- `bytes=-0` é válido, mas insatisfatível. Um sufixo positivo em uma representação de tamanho zero é **satisfatível** e retorna `(0, 0)`, conforme o RFC 9110 §14.1.2. Verifique `satisfiable` explicitamente.

Aumentar os limites permite mais trabalho de CPU e memória. A ferramenta não escolhe respostas HTTP, não gera `Content-Range` ou multipart, não baixa conteúdo e não implementa servidor, validação condicional ou leitura de arquivos. Essas decisões ficam com a aplicação.

## Verificação e licença

No Linux com `bubblewrap` e namespaces de usuário disponíveis:

```sh
python checks-offline.py
```

O executor monta somente o runtime Python e os diretórios públicos de código, testes e exemplos, com acesso de leitura. Isola a rede, limpa o ambiente e verifica ausência de capacidades, privilégios novos, diretórios pessoais, metadados Git e dispositivos de GPU. Se o sistema impedir o isolamento, a verificação falha. A CI cobre Python 3.10, 3.12 e 3.14.

Para verificar um wheel já preparado com `pip install --no-deps --target DIRETORIO_TEMPORARIO pacote.whl`, execute `python checks-offline.py --installed-package DIRETORIO_TEMPORARIO`. O diretório deve ser novo. Esse modo omite `src`, confirma a origem do módulo importado e executa os mesmos testes, exemplos e comando instalado dentro do isolamento. A CI prepara o wheel e o diretório temporário antes dessa etapa; instruções completas estão no README em inglês.

A CI em runners Linux hospedados pelo GitHub seleciona explicitamente `--github-hosted-runner`. Após conferir o ambiente, esse modo usa `sudo -n` somente para o bootstrap do bubblewrap do sistema, antes de criar os namespaces. A execução testada mantém os namespaces, a rede isolada e as montagens de leitura; antes de importar o pacote, confirma o UID/GID numérico do runner, capacidades efetivas zeradas e `NoNewPrivs=1`. Nenhuma configuração global de sysctl ou AppArmor é alterada. Esse modo é exclusivo dos runners efêmeros hospedados pelo GitHub; a execução local continua sem sudo.

Implementação original com referência ao [RFC 9110 §14.1.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.1.1), [§14.1.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.1.2), [§14.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.2), [§5.6.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.1) e [§5.6.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.3). Nenhum texto ou código do RFC foi copiado. As políticas de limites, ASCII, API e CLI pertencem ao projeto.

Licença MIT, copyright 2026 Martin. Veja [LICENSE](LICENSE).
