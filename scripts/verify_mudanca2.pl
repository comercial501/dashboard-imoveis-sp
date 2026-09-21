#!/usr/bin/perl
use strict; use warnings; use utf8;
use JSON::PP;
use FindBin qw($Bin);
binmode(STDOUT, ':encoding(UTF-8)');

open(my $fh, '<:encoding(UTF-8)', "$Bin/../data/dashboard_data.json") or die $!;
local $/; my $j = <$fh>;
my $d = JSON::PP->new->decode($j);

print "META: ", join(', ', map {"$_=$d->{meta}{$_}"} sort keys %{$d->{meta}}), "\n\n";

my @ca = @{$d->{captacao_ativa}};
print "Total captacao_ativa: ", scalar(@ca), "\n";
my $com_venda_hoje = grep { $_->{tem_unidade_a_venda_hoje} } @ca;
print "Com unidade a venda hoje: $com_venda_hoje\n\n";

print "=== Top 15 por n_vendas (qualquer bairro) ===\n";
my @sorted = sort { $b->{n_vendas} <=> $a->{n_vendas} } @ca;
for my $c (@sorted[0..14]) {
    printf("%-20s %-40s n=%-4d preco=%s-%s hoje=%s\n",
        $c->{bairro}, $c->{endereco}, $c->{n_vendas},
        fmt($c->{preco_min}), fmt($c->{preco_max}), $c->{tem_unidade_a_venda_hoje}?'SIM':'nao');
}

print "\n=== Moema (primeiros 5 ordenados por vendas) ===\n";
my @moema = grep { $_->{bairro} eq 'Moema' } @ca;
for my $c (@moema[0..4]) {
    printf("  %-40s n=%-4d preco=%s-%s hoje=%s codigos=%s\n",
        $c->{endereco}, $c->{n_vendas}, fmt($c->{preco_min}), fmt($c->{preco_max}),
        $c->{tem_unidade_a_venda_hoje}?'SIM':'nao',
        join(',', map { $_->{codigo}//'?' } @{$c->{unidades_a_venda_hoje}}));
}

print "\n=== Liquidez total vs revenda (2025), amostra ===\n";
for my $b ('Tatuapé', 'Moema', 'Pompéia', 'Vila Olímpia', 'Consolação') {
    my $x = $d->{bairros}{$b};
    printf("%-16s liquidez_total_2025=%-5s liquidez_revenda_2025=%-5s (diferenca=%d)\n",
        $b, $x->{liquidez_total_2025}, $x->{liquidez_revenda_2025}, $x->{liquidez_total_2025}-$x->{liquidez_revenda_2025});
}

sub fmt { my ($n) = @_; return sprintf('%.0f', $n); }
