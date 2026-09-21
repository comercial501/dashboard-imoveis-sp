#!/usr/bin/perl
use strict; use warnings; use utf8;
use JSON::PP;
use FindBin qw($Bin);
binmode(STDOUT, ':encoding(UTF-8)');

open(my $fh, '<:encoding(UTF-8)', "$Bin/../data/dashboard_data.json") or die $!;
local $/; my $j = <$fh>;
my $d = JSON::PP->new->decode($j);
my $bairros = $d->{bairros};

my %count_rel;
for my $b (keys %$bairros) { $count_rel{$bairros->{$b}{profile_reliability}}++; }
print "Distribuicao profile_reliability: ", join(', ', map {"$_=$count_rel{$_}"} sort keys %count_rel), "\n";
my %count_area_rel;
for my $b (keys %$bairros) { $count_area_rel{$bairros->{$b}{area_band_reliability}}++; }
print "Distribuicao area_band_reliability: ", join(', ', map {"$_=$count_area_rel{$_}"} sort keys %count_area_rel), "\n\n";

for my $b ('Tatuapé', 'Jardim Caravelas', 'Jardins', 'Jardim Novo Mundo', 'Vila Firmiano Pinto', 'Ibirapuera', 'Lapa', 'Moema') {
    my $x = $bairros->{$b} or next;
    print "== $b ==\n";
    print "  area_band: ", (defined $x->{area_band} ? "$x->{area_band}[0]-$x->{area_band}[1]" : 'N/A'), " (", $x->{area_band_reliability}, ")\n";
    if (@{$x->{area_band_neighbors}}) {
        print "    vizinhos usados p/ area: ", join(', ', map { "$_->{bairro} (${\ $_->{distancia_km}}km, n=$_->{n_pares})" } @{$x->{area_band_neighbors}}), "\n";
    }
    print "  profile: quartos=", ($x->{profile_quartos}//'NA'), " vagas=", ($x->{profile_vagas}//'NA'),
          " own_sample=$x->{profile_sample_size} pool_sample=$x->{profile_pool_sample_size} (", $x->{profile_reliability}, ")\n";
    if (@{$x->{profile_neighbors}}) {
        print "    vizinhos usados p/ perfil: ", join(', ', map { "$_->{bairro} (${\ $_->{distancia_km}}km, n=$_->{n_imoveis})" } @{$x->{profile_neighbors}}), "\n";
    }
    print "  flag_oportunidade=", ($x->{flag_oportunidade}?'Sim':'Nao'), " stock_matching_profile=$x->{stock_matching_profile} volume_2025=$x->{volume_2025}\n";
    print "\n";
}

print "Bairros ainda 'insufficient' em profile:\n";
for my $b (sort keys %$bairros) {
    print "  $b\n" if $bairros->{$b}{profile_reliability} eq 'insufficient';
}
print "\nBairros ainda 'insufficient' em area_band:\n";
for my $b (sort keys %$bairros) {
    print "  $b\n" if $bairros->{$b}{area_band_reliability} eq 'insufficient';
}
