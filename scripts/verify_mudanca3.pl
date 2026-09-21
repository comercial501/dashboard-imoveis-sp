#!/usr/bin/perl
use strict; use warnings; use utf8;
use JSON::PP;
use FindBin qw($Bin);
binmode(STDOUT, ':encoding(UTF-8)');

open(my $fh, '<:encoding(UTF-8)', "$Bin/../data/dashboard_data.json") or die $!;
local $/; my $j = <$fh>;
my $d = JSON::PP->new->decode($j);
my @im = @{$d->{imoveis_prioritarios}};

print "Total: ", scalar(@im), "\n\n";
print "=== TOP 10 ===\n";
for my $i (0..9) {
    my $x = $im[$i];
    printf("%2d. [%.1f] %-14s %-40s R\$%-10s %sq/%sv/%sm2  bairro_rev=%.1f preco=%.1f perfil=%.1f capt=%s\n  resumo: %s\n\n",
        $i+1, $x->{final_score}, $x->{bairro}, $x->{endereco}, fmt($x->{valor}),
        $x->{quartos}//'?', $x->{vagas}//'?', $x->{area}//'?',
        $x->{score_bairro_revenda}, $x->{price_alignment}, $x->{profile_adherence},
        $x->{tem_captacao_ativa}?'sim':'nao', $x->{resumo});
}

print "=== Exemplo de preco muito abaixo (zona cautela) ===\n";
my @cautela = grep { $_->{resumo} =~ /vale checar/ } @im;
print scalar(@cautela), " imoveis na zona de cautela de preco\n";
for my $x (@cautela[0..2]) {
    printf("  [%.1f] %-14s %-40s preco_align=%.1f resumo: %s\n", $x->{final_score}, $x->{bairro}, $x->{endereco}, $x->{price_alignment}, $x->{resumo}) if $x;
}

print "\n=== Distribuicao final_score ===\n";
my @scores = map { $_->{final_score} } @im;
@scores = sort { $a <=> $b } @scores;
print "min=$scores[0] p25=$scores[int(@scores*0.25)] mediana=$scores[int(@scores*0.5)] p75=$scores[int(@scores*0.75)] max=$scores[-1]\n";

sub fmt { my ($n) = @_; return sprintf('%.0f', $n//0); }
