#!/usr/bin/perl
# Compara dois dashboard_data.json (anterior x novo) e imprime um resumo do
# que mudou. Usado pelo atualizar.sh — ver README.md.
use strict;
use warnings;
use utf8;
use JSON::PP;

binmode(STDOUT, ':encoding(UTF-8)');
binmode(STDERR, ':encoding(UTF-8)');

my ($old_path, $new_path) = @ARGV;
die "uso: compare_runs.pl <json_anterior> <json_novo>\n" unless $old_path && $new_path;

sub load_json {
    my ($path) = @_;
    open(my $fh, '<:encoding(UTF-8)', $path) or die "nao consegui abrir $path: $!";
    local $/;
    my $content = <$fh>;
    close $fh;
    return JSON::PP->new->decode($content);
}

my $old = load_json($old_path);
my $new = load_json($new_path);

print "\n========================================\n";
print "RESUMO DA ATUALIZACAO\n";
print "========================================\n\n";

my $old_itbi = $old->{meta}{total_itbi_rows_matched} // 0;
my $new_itbi = $new->{meta}{total_itbi_rows_matched} // 0;
printf("Transacoes residenciais (ITBI): %s -> %s (%s%d)\n",
    commafy($old_itbi), commafy($new_itbi), ($new_itbi-$old_itbi>=0?'+':''), $new_itbi-$old_itbi);

my $old_usn = $old->{meta}{usn_rows_matched} // 0;
my $new_usn = $new->{meta}{usn_rows_matched} // 0;
printf("Anuncios ativos (Usenonstop): %s -> %s (%s%d)\n",
    commafy($old_usn), commafy($new_usn), ($new_usn-$old_usn>=0?'+':''), $new_usn-$old_usn);

if (@{ $new->{meta}{avisos_descoberta} // [] }) {
    print "\nAvisos de descoberta de arquivos nesta rodada:\n";
    print "  - $_\n" for @{ $new->{meta}{avisos_descoberta} };
}

# --- Ranking movers (>= 3 posicoes) ---
my %old_pos; my $i = 0;
$old_pos{$_} = $i++ for @{ $old->{ranking} // [] };
my %new_pos; $i = 0;
$new_pos{$_} = $i++ for @{ $new->{ranking} // [] };

my @movers;
for my $b (keys %new_pos) {
    next unless exists $old_pos{$b};
    my $delta = $old_pos{$b} - $new_pos{$b}; # positivo = subiu
    push @movers, { bairro => $b, delta => $delta, old => $old_pos{$b}, new => $new_pos{$b} } if abs($delta) >= 3;
}
@movers = sort { abs($b->{delta}) <=> abs($a->{delta}) } @movers;

print "\nMudancas no Ranking de Oportunidade (movimentos de 3+ posicoes):\n";
if (@movers) {
    for my $m (@movers) {
        my $arrow = $m->{delta} > 0 ? '^' : 'v';
        printf("  %s %-24s #%d -> #%d (%s%d)\n", $arrow, $m->{bairro}, $m->{old}+1, $m->{new}+1,
            ($m->{delta}>0?'subiu ':'caiu '), abs($m->{delta}));
    }
} else {
    print "  (nenhuma mudanca significativa)\n";
}

my @new_bairros = grep { !exists $old_pos{$_} } keys %new_pos;
my @removed_bairros = grep { !exists $new_pos{$_} } keys %old_pos;
if (@new_bairros) { print "  Bairros novos no ranking: ", join(', ', @new_bairros), "\n"; }
if (@removed_bairros) { print "  Bairros que sairam do ranking: ", join(', ', @removed_bairros), "\n"; }

# --- Prontidao para Campanha por Bairro: ranking movers (>= 3 posicoes) ---
# Mesma logica do Ranking de Oportunidade acima, mesmo limiar de ruido minimo.
my %old_prontidao_pos; $i = 0;
$old_prontidao_pos{$_} = $i++ for @{ $old->{prontidao_ranking} // [] };
my %new_prontidao_pos; $i = 0;
$new_prontidao_pos{$_} = $i++ for @{ $new->{prontidao_ranking} // [] };

my @prontidao_movers;
for my $b (keys %new_prontidao_pos) {
    next unless exists $old_prontidao_pos{$b};
    my $delta = $old_prontidao_pos{$b} - $new_prontidao_pos{$b}; # positivo = subiu
    push @prontidao_movers, { bairro => $b, delta => $delta, old => $old_prontidao_pos{$b}, new => $new_prontidao_pos{$b} } if abs($delta) >= 3;
}
@prontidao_movers = sort { abs($b->{delta}) <=> abs($a->{delta}) } @prontidao_movers;

print "\nMudancas na Prontidao para Campanha por Bairro (movimentos de 3+ posicoes):\n";
if (@prontidao_movers) {
    for my $m (@prontidao_movers) {
        my $arrow = $m->{delta} > 0 ? '^' : 'v';
        printf("  %s %-24s #%d -> #%d (%s%d)\n", $arrow, $m->{bairro}, $m->{old}+1, $m->{new}+1,
            ($m->{delta}>0?'subiu ':'caiu '), abs($m->{delta}));
    }
} else {
    print "  (nenhuma mudanca significativa)\n";
}

my @new_prontidao_bairros = grep { !exists $old_prontidao_pos{$_} } keys %new_prontidao_pos;
my @removed_prontidao_bairros = grep { !exists $new_prontidao_pos{$_} } keys %old_prontidao_pos;
if (@new_prontidao_bairros) { print "  Bairros novos no ranking: ", join(', ', @new_prontidao_bairros), "\n"; }
if (@removed_prontidao_bairros) { print "  Bairros que sairam do ranking: ", join(', ', @removed_prontidao_bairros), "\n"; }

# --- Divergencia entre os dois rankings ---
# Bairro que muda de direcao entre um ranking e outro (sobe num, desce no
# outro) e o sinal mais acionavel: indica que a prioridade de investimento
# pode estar mudando de liquidez pura para prontidao real de campanha, ou
# vice-versa. Exige sinais opostos E pelo menos um dos dois deltas cruzando o
# mesmo limiar de ruido minimo (3+ posicoes) usado acima, para nao poluir o
# resumo com micro-oscilacoes nos dois rankings ao mesmo tempo.
my @divergencias;
for my $b (keys %new_pos) {
    next unless exists $old_pos{$b} && exists $new_prontidao_pos{$b} && exists $old_prontidao_pos{$b};
    my $delta_r = $old_pos{$b} - $new_pos{$b};
    my $delta_p = $old_prontidao_pos{$b} - $new_prontidao_pos{$b};
    next unless $delta_r != 0 && $delta_p != 0;
    next unless (($delta_r > 0) != ($delta_p > 0)); # sinais opostos
    next unless abs($delta_r) >= 3 || abs($delta_p) >= 3;
    push @divergencias, {
        bairro => $b, delta_r => $delta_r, delta_p => $delta_p,
        old_r => $old_pos{$b}, new_r => $new_pos{$b},
        old_p => $old_prontidao_pos{$b}, new_p => $new_prontidao_pos{$b},
    };
}
@divergencias = sort { (abs($b->{delta_r})+abs($b->{delta_p})) <=> (abs($a->{delta_r})+abs($a->{delta_p})) } @divergencias;

print "\nDivergencia entre Ranking de Oportunidade e Prontidao (sinais opostos):\n";
if (@divergencias) {
    for my $d (@divergencias) {
        my $r_word = $d->{delta_r} > 0 ? 'subiu' : 'caiu';
        my $p_word = $d->{delta_p} > 0 ? 'subiu' : 'caiu';
        printf("  ~ %-24s Ranking de Oportunidade %s (#%d->#%d) | Prontidao %s (#%d->#%d)\n",
            $d->{bairro}, $r_word, $d->{old_r}+1, $d->{new_r}+1, $p_word, $d->{old_p}+1, $d->{new_p}+1);
    }
} else {
    print "  (nenhuma divergencia de direcao entre os dois rankings)\n";
}

# --- Top 20 "Imoveis Prioritarios" diff (por codigo do anuncio) ---
sub imovel_key {
    my ($r) = @_;
    return $r->{codigo} if defined $r->{codigo} && length($r->{codigo});
    return join('|', $r->{bairro}//'', $r->{endereco}//'', $r->{valor}//'');
}

my @old_top20 = @{ $old->{imoveis_prioritarios} // [] }[0..19];
my @new_top20 = @{ $new->{imoveis_prioritarios} // [] }[0..19];
@old_top20 = grep { defined } @old_top20;
@new_top20 = grep { defined } @new_top20;

my %old_keys = map { imovel_key($_) => $_ } @old_top20;
my %new_keys = map { imovel_key($_) => $_ } @new_top20;

my @entered = grep { !exists $old_keys{$_} } keys %new_keys;
my @left    = grep { !exists $new_keys{$_} } keys %old_keys;

print "\nImoveis que entraram no Top 20 de \"Imoveis Prioritarios\":\n";
if (@entered) {
    for my $k (@entered) {
        my $r = $new_keys{$k};
        printf("  + %-40s (%s) - score %.1f\n", $r->{endereco}//'?', $r->{bairro}//'?', $r->{final_score}//0);
    }
} else {
    print "  (nenhum)\n";
}
printf("(%d imoveis saíram do Top 20)\n", scalar(@left));

print "\n========================================\n\n";

sub commafy {
    my ($n) = @_;
    1 while $n =~ s/(\d)(\d{3})(?!\d)/$1.$2/;
    return $n;
}
