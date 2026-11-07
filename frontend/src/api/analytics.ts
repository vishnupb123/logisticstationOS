import { api } from "./client";
import type {
  EndToEndStats,
  InductThroughputBucket,
  JackpotVolumeReading,
  ParcelDwellTimeStats,
  StowThroughputBucket,
  WipsReading,
} from "./types";

export const analyticsApi = {
  jackpotVolume: () => api.get<JackpotVolumeReading>("/analytics/jackpot-volume"),
  wips: () => api.get<WipsReading>("/analytics/wips"),
  inductThroughput: () => api.get<InductThroughputBucket[]>("/analytics/induct-throughput"),
  stowThroughput: () => api.get<StowThroughputBucket[]>("/analytics/stow-throughput"),
  parcelDwellTime: () => api.get<ParcelDwellTimeStats>("/analytics/parcel-dwell-time"),
  endToEnd: () => api.get<EndToEndStats>("/analytics/end-to-end"),
};
