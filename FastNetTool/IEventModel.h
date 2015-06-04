#ifndef FASTNETTOOL_IEVENTMODEL_H
#define FASTNETTOOL_IEVENTMODEL_H
#include <vector>

#include "Rtypes.h"
#include "TObject.h"

struct IEventModel : public TObject {

  int             RunNumber;
  Float_t         el_pt;
  Float_t         el_eta;
  Float_t         el_phi;
  bool            el_loose;
  bool            el_medium;
  bool            el_tight;
  bool            el_lhLoose;
  bool            el_lhMedium;
  bool            el_lhTight;
  bool            el_multiLepton;
  int             trk_nPileupPrimaryVtx;
  Float_t         trig_L1_emClus;
  bool            trig_L1_accept;
  std::vector<float>  *trig_L2_calo_rings;
  bool            trig_L2_calo_accept;
  bool            trig_L2_el_accept;
  bool            trig_EF_calo_accept;
  bool            trig_EF_el_accept;
  bool            mc_hasMC;
  bool            mc_isElectron;
  bool            mc_hasZMother;

  ClassDef(IEventModel,1);
};

#endif // FASTNETTOOL_IEVENTMODEL_H
