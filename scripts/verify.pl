#!/usr/bin/perl
use strict; use warnings; use utf8;
use JSON::PP;
use FindBin qw($Bin);
binmode(STDOUT, ':encoding(UTF-8)');

open(my $fh, '<:encoding(UTF-8)', "$Bin/../data/dashboard_data.json") or die $!;
local $/; my $j = <$fh>;
my $d = JSON::PP->new->decode($j);

print "META: ", join(', ', map { "$_=$d->{meta}{$_}" } sort keys %{$d->{meta}}), "\n\n";

print "=== RANKING (top 15) ===\n";
my $i = 0;
for my $b (@{$d->{ranking}}) {
    last if $i++ >= 15;
    my $x = $d->{bairros}{$b};
    printf("%2d. %-24s score=%-6s vol25=%-5s trend=%-8s trend_used=%-8s stockTot=%-4s match=%-4s ratio=%-6s gap=%-7s%% %s%s\n",
        $i, $b, $x->{score}, $x->{volume_2025},
        defined($x->{trend_pct}) ? sprintf('%.0f%%', $x->{trend_pct}*100) : 'NA',
        defined($x->{trend_pct_for_score}) ? sprintf('%.0f%%', $x->{trend_pct_for_score}*100) : 'NA',
        $x->{stock_total}, $x->{stock_matching_profile}, $x->{stock_demand_ratio},
        defined($x->{price_gap_pct}) ? $x->{price_gap_pct} : 'NA',
        $x->{flag_oportunidade} ? '[OPORTUNIDADE]' : '', $x->{flag_alerta} ? '[ALERTA]' : '');
}

print "\n=== BOTTOM 10 ===\n";
my @rk = @{$d->{ranking}};
for my $b (@rk[-10..-1]) {
    my $x = $d->{bairros}{$b};
    printf("    %-24s score=%-6s vol25=%-5s\n", $b, $x->{score}, $x->{volume_2025});
}

print "\n=== Perfil vencedor / estoque (amostra) ===\n";
for my $b ('Moema', 'Vila Madalena', 'Brooklin', 'Pompéia', 'Jardins', 'Jardim Novo Mundo', 'Vila Firmiano Pinto') {
    my $x = $d->{bairros}{$b} or do { print "$b: SEM DADOS (bug!)\n"; next; };
    printf("%-22s area_band=%-12s price_band=%-24s quartos=%-4s vagas=%-4s sample=%-4s stockTot=%-4s centroid=%s\n",
        $b,
        (defined $x->{area_band} ? "$x->{area_band}[0]-$x->{area_band}[1]" : 'N/A'),
        (defined $x->{price_band} ? sprintf('%.0f-%.0f', @{$x->{price_band}}) : 'N/A'),
        $x->{profile_quartos} // 'NA', $x->{profile_vagas} // 'NA', $x->{profile_sample_size} // 0,
        $x->{stock_total} // 0,
        (defined $x->{centroid} ? sprintf('%.4f,%.4f', @{$x->{centroid}}) : 'N/A'));
}

print "\nTotal bairros no ranking: ", scalar(@{$d->{ranking}}), " (esperado: 46)\n";
my @missing = grep { !exists $d->{bairros}{$_} } @{$d->{ranking}};
print "Bairros sem entrada em 'bairros': ", scalar(@missing), "\n";
